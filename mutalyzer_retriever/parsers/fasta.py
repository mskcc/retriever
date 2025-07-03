from io import StringIO

from Bio import SeqIO


def parse(fasta):
    records = []
    for record in SeqIO.parse(StringIO(fasta), "fasta"):
        records.append({"seq": str(record.seq), "description": record.description})
    if not records:
        raise ValueError
    if len(records) == 1:
        return records[0]


def parse_large(fasta):
    print("Loading the fasta, this may take some time...")
    return SeqIO.index(fasta, "fasta")
