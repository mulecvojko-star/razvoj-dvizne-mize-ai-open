"""Render previously saved result.json or completed cycle ledger without any model."""

import argparse
from pathlib import Path
from .package import build_package
from .source import load


def main():
    parser=argparse.ArgumentParser(description="Tehnični razvojni paket iz obstoječega JSON – brez AI-klica")
    parser.add_argument("input",type=Path)
    parser.add_argument("--output-dir",type=Path,default=Path("packages"))
    parser.add_argument("--metadata-dir",type=Path,help="Imenik izvornega artifacta z manifest.json, report.json in runs/")
    args=parser.parse_args()
    try:
        document,metadata=load(args.input,args.metadata_dir)
        path=build_package(document,args.output_dir,metadata=metadata)
    except (ValueError,OSError):
        parser.exit(1,"Paket ni ustvarjen. Potreben je popoln uspešen sintetični cikel; preveri vhod in odvisnosti.\n")
    print(f"Razvojni paket: {path}")


if __name__ == "__main__":
    main()
