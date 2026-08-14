from __future__ import annotations
import unittest
from avo.timeline.lineage import LineageError,validate_bmap_basis
class BMapBasisTests(unittest.TestCase):
    def test_requires_latest_approved_exact_output(self):
        cmap={"currentRevisionId":"c2","approvedRevisionId":"c2","revisions":[{"revisionId":"c2","contentHash":"a"*64}],"decisions":[{"revisionId":"c2","revisionHash":"a"*64,"candidateHash":"b"*64,"decision":"approved"}]}
        validate_bmap_basis({"revisionId":"c2","sha256":"a"*64,"outputSha256":"b"*64},cmap)
        with self.assertRaises(LineageError): validate_bmap_basis({"revisionId":"c1","sha256":"a"*64,"outputSha256":"b"*64},cmap)
