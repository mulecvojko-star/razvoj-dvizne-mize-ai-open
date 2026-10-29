"""Atomic offline ZIP creation; no AI imports, calls or revision creation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from .source import PackageError, prepare

FILES = ("00_Povzetek.pdf", "01_Konstruktor.pdf", "02_Hidravlik.pdf", "03_Ekonomist.xlsx",
         "04_Recenzent.pdf", "05_Izvorni_podatki.json")


def build_package(document, output_dir, *, metadata=None):
    handoff, source = prepare(document, metadata)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{handoff.label}_Razvojni_paket.zip"
    try:
        from .documents import make_pdfs, make_excel
        with TemporaryDirectory(prefix=".paket-", dir=output_dir) as temporary:
            root = Path(temporary)
            make_pdfs(root, handoff, source["provenance"])
            make_excel(root/"03_Ekonomist.xlsx", handoff)
            (root/"05_Izvorni_podatki.json").write_text(json.dumps(source,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
            archive = root / destination.name
            with ZipFile(archive,"w",ZIP_DEFLATED) as zipfile:
                for name in FILES:
                    zipfile.write(root/name, name)
            with ZipFile(archive) as zipfile:
                if zipfile.testzip() is not None or set(zipfile.namelist()) != set(FILES):
                    raise PackageError("Razvojni ZIP ni veljaven.")
            archive.replace(destination)
    except PackageError:
        raise
    except Exception:
        raise PackageError("Izdelava dokumentov ni uspela; celoten ZIP ni bil objavljen. Uporabi shranjeni JSON za ponoven poskus brez agentov.") from None
    return destination
