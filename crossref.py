from io import StringIO
import re
import json
import bibtexparser as bp
from bibtexparser.bibdatabase import BibDataStringExpression, BibDataString, as_text
from bibfmt import _parser, _writer
from pprint import pprint

with open("krr.bib", "r") as f:
    in_ = f.read()
db = bp.loads(in_, _parser())
with open("procs.bib", "r") as f:
    in_ = f.read()
procs = bp.loads(in_, _parser())


proceeding_titles = {}
bib_strings = {}

for entry in procs.entries:
    if 'title' in entry:
        title = entry['title']
    elif 'booktitle' in entry:
        title = entry['title']
    else:
        continue
    proceeding_titles[title] = entry['ID']

for s, bs in db.strings.items():
    bib_strings[bs] = BibDataStringExpression([BibDataString(db, s)])

# pprint(proceeding_titles)
# pprint(bib_strings)


for entry in db.entries:
    # if 'journal' in entry and isinstance(entry['journal'], str) and entry['journal'] in bib_strings:
    #     entry['journal'] = bib_strings[entry['journal']]
    if 'booktitle' in entry and isinstance(entry['booktitle'], str) and entry['booktitle'] in proceeding_titles:
        entry['crossref'] = proceeding_titles[entry['booktitle']]

with open("krr.bib", "w") as f:
    bp.dump(db, f, _writer())
        