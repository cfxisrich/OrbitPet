from pathlib import Path

project = Path(SPECPATH)
analysis = Analysis(
    [str(project / "app.py")],
    pathex=[str(project)],
    datas=[(str(project / "assets"), "assets")],
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="OrbitPet",
    console=False,
    icon=str(project / "assets" / "orbit.ico"),
    upx=False,
)
