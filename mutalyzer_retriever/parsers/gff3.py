"""
Module for gff files parsing.

GFF3 specifications:
- Official:
  - [1] https://github.com/The-Sequence-Ontology/Specifications/blob/master/gff3.md
- NCBI:
  - [2]: ftp://ftp.ncbi.nlm.nih.gov/genomes/README_GFF3.txt
  - https://www.ncbi.nlm.nih.gov/genbank/genomes_gff/
- Ensembl:
  - ftp://ftp.ensembl.org/pub/release-98/gff3/homo_sapiens/README

Download ftp:
- ftp://ftp.ensembl.org/pub/current_gff3/homo_sapiens/
- ftp://ftp.ensembl.org/pub/release-98/gff3/homo_sapiens/

Sequence Ontology Feature Annotation (SOFA):
- http://www.sequenceontology.org/so_wiki/index.php/FAQ

Notes:
    - GFF files have 9 columns, not explicitly mentioned in the file, tab
    delimited, with the following order: seqid, source, type, start, end,
    score, strand, phase, and attributes.
    - According to the official specifications, there can be multiple parents
    for one entry, e.g., for exons. However, it seems like NCBI does not adhere
    to this practice.
    - Multiple entries can have the same parent.
    - There are entries with no parents.
    - '#' is used for comments.
    - mRNA and gene ID fields in the attributes column are unique.
    - CDS ID fields in the attributes column are not unique. However, the CDS
    entries with the same ID are part of the same protein. They are split like
    this in the same manner as the exons are.
"""

import io

from BCBio.GFF import GFFParser
from Bio.SeqUtils import seq1

from ..util import make_location

CONSIDERED_TYPES = [
    "gene",
    "ncRNA_gene",
    "mRNA",
    "exon",
    "CDS",
    "lnc_RNA",
    "snRNA",
    "polypeptide",
]
QUALIFIERS = {
    "gene": {
        "Name": "name",
        "gene_synonym": "synonym",
        "version": "version",
        "assembly_name": "assembly_name",
    },
    "ncRNA_gene": {
        "Name": "name",
        "gene_synonym": "synonym",
        "version": "version",
        "assembly_name": "assembly_name",
    },
    "region": {
        "organism": "organism",
        "mol_type": "mol_type",
        "chromosome": "chromosome",
        "map": "map",
        "Dbxref": "dbxref",
        "Is_circular": "is_circular",
        "transl_table": "transl_table",
        "Name": "name",
        "genome": "genome",
    },
    "CDS": {
        "transl_except": "translation_exception",
        "exception": "exception",
    },
    "mRNA": {
        "version": "version",
        "assembly_name": "assembly_name",
        "tag": "tag",
    },
    "snRNA": {
        "version": "version",
        "assembly_name": "assembly_name",
    },
    "polypeptide": {"gbkey": "gbkey", "product": "product"},
}
SO_IDS = {
    "gene": "SO:0000704",
    "mRNA": "SO:0000234",
    "ncRNA": "SO:0000655",
    "exon": "SO:0000147",
    "CDS": "SO:0000316",
}


def _get_feature_id(feature):
    if feature.type in ["gene", "ncRNA_gene"]:
        if feature.qualifiers.get("gene_id"):
            return feature.qualifiers["gene_id"][0]
        elif feature.qualifiers.get("Name"):
            return feature.qualifiers["Name"][0]
    elif feature.type in ["mRNA", "lnc_RNA", "snRNA"]:
        if feature.qualifiers.get("transcript_id"):
            return feature.qualifiers["transcript_id"][0]
    elif feature.type == "CDS" and feature.qualifiers.get("protein_id"):
        return feature.qualifiers["protein_id"][0]
    elif feature.type == "exon":
        if feature.qualifiers.get("exon_id"):
            return feature.qualifiers["exon_id"][0]
        elif feature.id:
            return feature.id
    elif feature.type == "polypeptide":
        return feature.id.split("-")[1].split(":")[0]


def _combine_cdses(mrna):
    """
    Combine all the cds features into a single one.
    """
    positions = []
    exons = []
    for feature in mrna["features"]:
        if feature["type"] == "CDS":
            positions.append(feature["location"]["start"]["position"])
            positions.append(feature["location"]["end"]["position"])
        elif feature["type"] == "exon":
            exons.append(feature)
    positions = sorted(positions)
    for feature in mrna["features"]:
        if feature["type"] == "CDS":
            feature["location"]["start"]["position"] = positions[0]
            feature["location"]["end"]["position"] = positions[-1]
            mrna["features"] = exons + [feature]
            return


def _extract_translation_exception(translation_exception):
    output = []

    if isinstance(translation_exception, str):
        translation_exception = [translation_exception]

    for t_e in translation_exception:
        pos, aa = t_e.strip("()").split(",")

        if "complement" in pos:
            strand = -1
            if ".." in pos:
                pos_start, pos_end = pos.split("(")[1].strip(")").split("..")
            else:
                pos_start = pos.split("(")[1].strip(")")
                pos_end = None
        else:
            strand = 1
            if ".." in pos:
                pos_start, pos_end = pos.split(":")[1].split("..")
            else:
                pos_start = pos.split(":")[1]
                pos_end = None

        pos_start = int(pos_start) - 1
        if pos_end is not None:
            pos_end = int(pos_end)

        if ":" in aa:
            aa = aa.split(":")[1]
        elif "=" in aa:
            aa = aa.split("=")[1]

        output.append(
            {
                "location": make_location(pos_start, pos_end, strand),
                "amino_acid": seq1(aa),
            }
        )
    return output


def _extract_special_qualifiers(qs):
    for q in qs:
        if q == "translation_exception":
            qs[q] = {"exceptions": _extract_translation_exception(qs[q])}


def _get_qualifiers(feature):
    q = feature.qualifiers
    t = feature.type
    if feature.type in QUALIFIERS.keys():
        qs = {
            QUALIFIERS[t][k]: q[k][0] if len(q[k]) == 1 else q[k]
            for k in q.keys()
            if k in QUALIFIERS[t].keys()
        }
        if t == "gene":
            if q.get("Dbxref"):
                for dbxref_entry in q["Dbxref"]:
                    if "HGNC" in dbxref_entry:
                        qs["HGNC"] = dbxref_entry.split(":")[-1]
        if t in ["mRNA", "CDS"]:
            if q.get("Dbxref"):
                for dbxref_entry in q["Dbxref"]:
                    if "Ensembl" in dbxref_entry:
                        qs["Ensembl"] = dbxref_entry.split(":")[-1]
        _extract_special_qualifiers(qs)
        return qs


def _get_feature_type(feature):
    if feature.type in ["gene"]:
        return "gene"
    elif feature.type in ["mRNA"]:
        return "mRNA"
    elif feature.type in ["lnc_RNA"]:
        return "ncRNA"
    elif feature.type in ["exon"]:
        return "exon"
    elif feature.type in ["CDS"]:
        return "CDS"
    else:
        return feature.type


def _get_feature_model(feature, considered_types=CONSIDERED_TYPES):
    """
    Recursively get the model for a particular feature.

    The method to combine CDSes into a single feature is also called.
    """

    if feature.type in considered_types:
        model = {
            "type": _get_feature_type(feature),
            "location": make_location(
                feature.location.start, feature.location.end, feature.location.strand
            ),
        }
        feature_id = _get_feature_id(feature)
        if feature_id:
            model["id"] = feature_id
        qualifiers = _get_qualifiers(feature)
        if qualifiers:
            model["qualifiers"] = qualifiers
        if feature.sub_features:
            model["features"] = []
            for sub_feature in feature.sub_features:
                sub_feature_model = _get_feature_model(
                    feature=sub_feature,
                    considered_types=considered_types,
                )
                if sub_feature_model:
                    model["features"].append(sub_feature_model)
        if feature.type == "mRNA":
            _combine_cdses(model)
        return model


def _get_record_features_model(record, considered_types=CONSIDERED_TYPES):
    features = []
    if record.features:
        for feature in record.features:
            feature_model = _get_feature_model(
                feature=feature,
                considered_types=considered_types,
            )
            if feature_model and feature_model.get("id"):
                features.append(feature_model)
    return features


def _get_region_model(features):
    """
    Multiple `region` features can be present in the file. According to
    the NCBI [2], the one that corresponds to the `source` feature that
    appears in a GenBank flatfile format can be identified by the
    `gbkey=Src` attribute and is the first feature row for every seqid.
    """
    for feature in features:
        if feature.type == "region" and feature.qualifiers.get("gbkey"):
            if feature.qualifiers["gbkey"][0] == "Src":
                return _get_feature_model(feature=feature, considered_types=["region"])


def _get_rna_features(record, mol_type):
    if mol_type == "mRNA":
        feature_type = "mRNA"
    else:
        feature_type = "ncRNA"
    rna_model = {"id": record.id, "type": feature_type}

    features = _get_record_features_model(
        record=record, considered_types=["gene", "exon", "CDS", "mRNA", "lnc_RNA"]
    )

    if features:
        exon_positions = []
        if features[0].get("features"):
            for sub_feature in features[0]["features"]:
                if sub_feature["type"] == "exon":
                    exon_positions.append(sub_feature["location"]["start"]["position"])
                    exon_positions.append(sub_feature["location"]["end"]["position"])
        if exon_positions:
            rna_model["location"] = make_location(
                sorted(exon_positions)[0], sorted(exon_positions)[-1]
            )
        else:
            rna_model["location"] = make_location(
                record.annotations["sequence-region"][0][1],
                record.annotations["sequence-region"][0][2],
            )
        if features[0].get("features"):
            if len(features[0]["features"]) == 1 and features[0]["features"][0].get(
                "type"
            ) in ["ncRNA", "mRNA"]:
                # e.g., M65131.1, XR_948219.2
                rna_model["features"] = features[0]["features"][0]["features"]
                features[0]["features"] = [rna_model]
            else:
                # e.g. NR_002196.2
                features_to_add = []
                for f in features[0]["features"]:
                    if f["type"] in ("exon", "CDS"):
                        features_to_add.append(f)
                rna_model["features"] = features_to_add
                features[0]["features"] = [rna_model]
        return features


def _create_record_model(record, source=None):
    """
    Our model follows the gene-mRNA-CDS/exon and gene-ncRNA-exon conventions.
    Annotations in GFF3 files also conform to this, with some exceptions:
    - `mol_type=*RNA` NCBI references (e.g., NM_/XM, NR_/XR), for which the
       RNA may be missing, leaving something like: gene-(CDS)/exon. In this
       case we create the '*RNA' feature between the gene and the CDS/exons.
       We observed that for mRNAs (e.g., NMs) the gene children consist of
       only the CDS and exons, while for other RNAs (e.g., NRs) there are
       other features as well (which we do not consider).
         - There are also examples where the gene-mRNA-(CDS)/exon nesting is
           present (M65131.1, XR_948219.2) or where gene-exon/lnc_RNA-exon
           (NR_002196.2).
    - There may be some floating exons attached directly to a gene. We do not
      add them to our model.
    """

    features = None
    region_model = _get_region_model(record.features)
    if region_model and region_model.get("qualifiers"):
        if region_model["qualifiers"].get("mol_type"):
            mol_type = region_model["qualifiers"]["mol_type"]
            if "RNA" in region_model["qualifiers"]["mol_type"].upper():
                # e.g., NCBI: NM_/NR_/...
                features = _get_rna_features(record, mol_type)
    if features is None:
        # e.g., ENST
        features = _get_record_features_model(record)

    model = {
        "id": record.id,
        "type": "record",
        "location": make_location(
            record.annotations["sequence-region"][0][1],
            record.annotations["sequence-region"][0][2],
        ),
    }

    if region_model and region_model.get("qualifiers"):
        model["qualifiers"] = region_model["qualifiers"]

    if features:
        model["features"] = features

    return model


def parse(gff_content, source=None, multi=False):
    gff_parser = GFFParser()
    gff = gff_parser.parse(io.StringIO(gff_content))

    records = []
    for record in gff:
        single_record = _create_record_model(record, source)
        records.append(single_record)
    if multi:
        return records
    if len(records) >= 1:
        return records[0]
