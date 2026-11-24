from pathlib import Path
import io, csv
ALLOWED={'.pdf','.docx','.txt','.md','.csv','.xlsx','.json'}
def extract(filename, raw):
    ext=Path(filename).suffix.lower()
    if ext not in ALLOWED: raise ValueError(f'Unsupported file type: {ext}')
    if ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw)); return '\n'.join(p.extract_text() or '' for p in reader.pages)
    if ext=='.docx':
        from docx import Document
        d=Document(io.BytesIO(raw)); return '\n'.join(p.text for p in d.paragraphs)+'\n'+'\n'.join(' | '.join(c.text for c in r.cells) for t in d.tables for r in t.rows)
    if ext=='.xlsx':
        from openpyxl import load_workbook
        wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True); out=[]
        for ws in wb.worksheets:
            out.append(f'[{ws.title}]')
            for row in ws.iter_rows(values_only=True): out.append(' | '.join('' if v is None else str(v) for v in row))
        return '\n'.join(out)
    return raw.decode('utf-8-sig',errors='replace')
