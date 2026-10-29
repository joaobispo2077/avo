# Code-drawn integration fixtures

Original synthetic geometry for browser/encoder conformance tests, covered by the repository license. No third-party footage, fonts, images, voices or music are included. The optional brush test uses the genuinely provisioned local standalone brush dependency through AVO's native scaffold, rather than a simulated brush.

The Canvas/SVG fixtures use a 128 x 96 surface, exact frame-derived drawing at 30000/1001 fps, a visible state boundary at frame six, and transparent/partial-alpha shapes. Tests replace the background token in a fresh external test composition and fingerprint the resulting source before capture.
