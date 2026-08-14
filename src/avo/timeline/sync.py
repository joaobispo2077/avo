"""Generic raw-based synchronization transforms and validation."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

class SyncError(ValueError): pass

@dataclass(frozen=True)
class ConstantOffset:
    offset_ticks:int
    timebase_num:int=1
    timebase_den:int=1000
    def audio_to_picture(self,audio_ticks:int)->int:return audio_ticks+self.offset_ticks
    def picture_to_audio(self,picture_ticks:int)->int:return picture_ticks-self.offset_ticks

@dataclass(frozen=True)
class LinearDrift:
    start_at:int;start_offset:int;end_at:int;end_offset:int
    @classmethod
    def from_points(cls,start:tuple[int,int],end:tuple[int,int])->"LinearDrift":
        if end[0]<=start[0]:raise SyncError("linear drift points must increase")
        return cls(start[0],start[1],end[0],end[1])
    def offset_at(self,ticks:int)->int:
        ratio=Fraction(ticks-self.start_at,self.end_at-self.start_at)
        return round(self.start_offset+ratio*(self.end_offset-self.start_offset))

class PiecewiseTransform:
    def __init__(self,points:list[tuple[int,int]]):
        if len(points)<2 or any(b[0]<=a[0] for a,b in zip(points,points[1:])):raise SyncError("piecewise control points must strictly increase")
        self.points=points
    def offset_at(self,ticks:int)->int:
        if ticks<=self.points[0][0]:return self.points[0][1]
        if ticks>=self.points[-1][0]:return self.points[-1][1]
        for a,b in zip(self.points,self.points[1:]):
            if a[0]<=ticks<=b[0]:return LinearDrift.from_points(a,b).offset_at(ticks)
        raise SyncError("no piecewise interval")

def validate_residuals(residuals:list[int],tolerance_ticks:int)->int:
    if not residuals:raise SyncError("full-program validation samples required")
    maximum=max(abs(v) for v in residuals)
    if maximum>tolerance_ticks:raise SyncError(f"maximum residual {maximum} exceeds tolerance {tolerance_ticks}")
    return maximum

def validate_raw_sync_basis(picture:dict[str,Any],audio:dict[str,Any])->None:
    if picture.get("kind")!="raw" or audio.get("kind")!="raw":raise SyncError("sync/resync must derive directly from raw picture and audio")

def build_constant_offset_snapshot(*,picture:dict[str,Any],audio:dict[str,Any],offset_ticks:int,timebase:dict[str,int],samples:list[tuple[int,int]],tolerance_ticks:int)->dict[str,Any]:
    validate_raw_sync_basis(picture,audio)
    residuals=[p-(a+offset_ticks) for p,a in samples]
    maximum=validate_residuals(residuals,tolerance_ticks)
    clean=lambda value:{k:v for k,v in value.items() if k!="kind"}
    return {"picture":clean(picture),"audio":clean(audio),"referenceClock":"picture","signConvention":"positive-audio-delay","transform":{"kind":"constant-offset","offsetTicks":offset_ticks,"timebase":timebase},"calibrationSamples":[{"pictureTicks":p,"audioTicks":a,"residualTicks":r} for (p,a),r in zip(samples,residuals)],"toleranceTicks":tolerance_ticks,"fullProgramValidation":{"status":"pass","maxResidualTicks":maximum}}

def validate_sync_snapshot(snapshot:dict[str,Any])->None:
    if snapshot.get("status")=="not-applicable":
        build_not_applicable_snapshot(raw_fingerprints=snapshot.get("rawFingerprints") or {},actor=str(snapshot.get("assessedBy") or ""),reason=str(snapshot.get("rationale") or ""));return
    validation=snapshot.get("fullProgramValidation") or {}
    if validation.get("status")!="pass":raise SyncError("sync approval requires full-program validation PASS")
    if int(validation.get("maxResidualTicks",10**18))>int(snapshot.get("toleranceTicks",-1)):raise SyncError("sync residual exceeds tolerance")
    transform=snapshot.get("transform") or {};kind=transform.get("kind")
    if kind not in {"constant-offset","linear-drift","piecewise"}:raise SyncError("unsupported sync transform")
    if snapshot.get("signConvention") not in {"positive-audio-delay","positive-audio-advance"}:raise SyncError("sync sign convention is ambiguous")


def build_linear_snapshot(*,picture:dict[str,Any],audio:dict[str,Any],rate_ratio:dict[str,int],offset_ticks:int,timebase:dict[str,int],samples:list[tuple[int,int,int]],tolerance_ticks:int)->dict[str,Any]:
    validate_raw_sync_basis(picture,audio)
    if int(rate_ratio.get("num",0))<=0 or int(rate_ratio.get("den",0))<=0:raise SyncError("linear drift rate ratio must be positive")
    residuals=[residual for _,_,residual in samples];maximum=validate_residuals(residuals,tolerance_ticks)
    clean=lambda value:{k:v for k,v in value.items() if k!="kind"}
    return {"picture":clean(picture),"audio":clean(audio),"referenceClock":"picture","signConvention":"positive-audio-delay","transform":{"kind":"linear-drift","offsetTicks":offset_ticks,"rateRatio":rate_ratio,"timebase":timebase},"calibrationSamples":[{"pictureTicks":p,"audioTicks":a,"residualTicks":r} for p,a,r in samples],"toleranceTicks":tolerance_ticks,"fullProgramValidation":{"status":"pass","maxResidualTicks":maximum}}


def build_piecewise_snapshot(*,picture:dict[str,Any],audio:dict[str,Any],control_points:list[dict[str,int]],timebase:dict[str,int],samples:list[tuple[int,int,int]],tolerance_ticks:int)->dict[str,Any]:
    validate_raw_sync_basis(picture,audio)
    if len(control_points)<2 or any(b["pictureTicks"]<=a["pictureTicks"] or b["audioTicks"]<=a["audioTicks"] for a,b in zip(control_points,control_points[1:])):raise SyncError("piecewise control points must strictly increase")
    residuals=[residual for _,_,residual in samples];maximum=validate_residuals(residuals,tolerance_ticks)
    clean=lambda value:{k:v for k,v in value.items() if k!="kind"}
    return {"picture":clean(picture),"audio":clean(audio),"referenceClock":"picture","signConvention":"positive-audio-delay","transform":{"kind":"piecewise","controlPoints":control_points,"timebase":timebase},"calibrationSamples":[{"pictureTicks":p,"audioTicks":a,"residualTicks":r} for p,a,r in samples],"toleranceTicks":tolerance_ticks,"fullProgramValidation":{"status":"pass","maxResidualTicks":maximum}}


def build_not_applicable_snapshot(*,raw_fingerprints:dict[str,str],actor:str,reason:str)->dict[str,Any]:
    import re
    if not raw_fingerprints or not actor.strip() or not reason.strip():raise SyncError("not-applicable Sync requires current raw basis, actor, and rationale")
    if any(not re.fullmatch(r"[a-f0-9]{64}",value) for value in raw_fingerprints.values()):raise SyncError("not-applicable raw fingerprint is invalid")
    return {"status":"not-applicable","rawFingerprints":dict(sorted(raw_fingerprints.items())),"assessedBy":actor,"rationale":reason,"policy":"single-muxed-clock-only"}
