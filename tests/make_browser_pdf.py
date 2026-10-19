"""Synthetic policy fixture without importing application configuration."""
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

writer = PdfWriter()
page = writer.add_blank_page(width=612, height=792)
page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"):
    DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                      NameObject("/BaseFont"): NameObject("/Helvetica")})})})
stream = DecodedStreamObject()
stream.set_data(b"BT /F1 12 Tf 50 700 Td (1. Returns require clear photographs of damaged items within seven days.) Tj ET")
page[NameObject("/Contents")] = writer._add_object(stream)
Path("artifacts").mkdir(exist_ok=True)
with Path("artifacts/pilot-policy.pdf").open("wb") as output:
    writer.write(output)
