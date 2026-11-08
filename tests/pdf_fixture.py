"""生成不含个人资料的最小文本 PDF，仅供自动检查使用。"""

from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject


def make_pdf(
    *, blank: bool = False, encrypted: bool = False, pages: int = 1,
    texts: list[str] | None = None, image_pages: set[int] | None = None,
    broken_pages: set[int] | None = None,
    table_pages: set[int] | None = None,
) -> bytes:
    """中文文本走真实字体映射；图像为合成像素，不含真实论文。页号从 1 开始。"""
    writer = PdfWriter()
    page_count = len(texts) if texts is not None else pages
    for index in range(page_count):
        page = writer.add_blank_page(width=595, height=842)
        text = texts[index] if texts is not None else (
            "" if blank else f"Synthetic course paper page {index + 1}. Evidence for workflow testing."
        )
        if text:
            chinese = any(ord(character) > 127 for character in text)
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            if chinese:
                descendant = DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/CIDFontType0"),
                    NameObject("/BaseFont"): NameObject("/STSong-Light"),
                    NameObject("/CIDSystemInfo"): DictionaryObject({
                        NameObject("/Registry"): TextStringObject("Adobe"),
                        NameObject("/Ordering"): TextStringObject("GB1"),
                        NameObject("/Supplement"): NumberObject(2),
                    }),
                    NameObject("/DW"): NumberObject(1000),
                    NameObject("/FontDescriptor"): writer._add_object(DictionaryObject({
                        NameObject("/Type"): NameObject("/FontDescriptor"),
                        NameObject("/FontName"): NameObject("/STSong-Light"),
                        NameObject("/Flags"): NumberObject(4),
                        NameObject("/FontBBox"): ArrayObject([NumberObject(n) for n in (0, -200, 1000, 900)]),
                        NameObject("/Ascent"): NumberObject(880), NameObject("/Descent"): NumberObject(-120),
                        NameObject("/CapHeight"): NumberObject(700), NameObject("/ItalicAngle"): NumberObject(0),
                        NameObject("/StemV"): NumberObject(80),
                    })),
                })
                chars = sorted(set(text) - {"\n"})
                mappings = "\n".join(
                    f"<{character.encode('utf-16-be').hex()}> <{character.encode('utf-16-be').hex()}>"
                    for character in chars
                )
                cmap = DecodedStreamObject()
                cmap.set_data((
                    "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                    "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
                    "/CMapName /TestUnicode def\n/CMapType 2 def\n"
                    "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
                    f"{len(chars)} beginbfchar\n{mappings}\nendbfchar\n"
                    "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
                ).encode("ascii"))
                font = DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type0"),
                    NameObject("/BaseFont"): NameObject("/STSong-Light"),
                    NameObject("/Encoding"): NameObject("/Identity-H"),
                    NameObject("/DescendantFonts"): ArrayObject([writer._add_object(descendant)]),
                    NameObject("/ToUnicode"): writer._add_object(cmap),
                })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({
                    NameObject("/F1"): writer._add_object(font),
                }),
            })
            commands = ["BT /F1 12 Tf 72 760 Td 18 TL"]
            for line in text.split("\n"):
                if chinese:
                    commands.append(f"<{line.encode('utf-16-be').hex()}> Tj T*")
                else:
                    escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                    commands.append(f"({escaped}) Tj T*")
            commands.append("ET")
            stream = DecodedStreamObject()
            stream.set_data("\n".join(commands).encode("ascii"))
            if broken_pages and index + 1 in broken_pages:
                stream[NameObject("/Filter")] = NameObject("/UnsupportedTestFilter")
            page[NameObject("/Contents")] = writer._add_object(stream)
        if image_pages and index + 1 in image_pages:
            image = DecodedStreamObject()
            image.set_data(b"\xff\xff\xff")
            image.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1), NameObject("/Height"): NumberObject(1),
                NameObject("/BitsPerComponent"): NumberObject(8),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            })
            resources = page.get("/Resources", DictionaryObject())
            resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Im1"): writer._add_object(image)})
            page[NameObject("/Resources")] = resources
            drawing = DecodedStreamObject()
            drawing.set_data(b"q 450 0 0 650 60 100 cm /Im1 Do Q")
            previous = page.get("/Contents")
            page[NameObject("/Contents")] = ArrayObject([previous, writer._add_object(drawing)]) if previous else writer._add_object(drawing)
        if table_pages and index + 1 in table_pages:
            commands = ["q 0.5 w"]
            for y in (500, 540, 580, 620):
                commands.append(f"72 {y} m 492 {y} l S")
            for x in (72, 212, 352, 492):
                commands.append(f"{x} 500 m {x} 620 l S")
            commands.append("Q")
            drawing = DecodedStreamObject()
            drawing.set_data("\n".join(commands).encode("ascii"))
            previous = page.get("/Contents")
            reference = writer._add_object(drawing)
            page[NameObject("/Contents")] = ArrayObject([previous, reference]) if previous else reference
    if encrypted:
        writer.encrypt("test-only-password")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
