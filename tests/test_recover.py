from palimpsest.recover import dedupe, kind_of, parse_fls
from palimpsest.models import Artifact

SAMPLE = """r/r * 1234:\tDCIM/IMG_0042.JPG
r/r * 1235:\tDCIM/IMG_0043.JPG
d/d * 1236:\tDCIM
r/r * 1237-128-2:\tDocuments/2021/letter.txt
r/r 1240:\tlive.txt
"""


def test_parse_fls_keeps_deleted_and_paths():
    entries = parse_fls(SAMPLE)
    assert len(entries) == 5
    first = entries[0]
    assert first.inode == "1234"
    assert first.path == "DCIM/IMG_0042.JPG"
    assert first.name == "IMG_0042.JPG"
    assert first.deleted


def test_parse_fls_flags_directories():
    entries = parse_fls(SAMPLE)
    assert entries[2].is_dir


def test_kind_by_extension(tmp_path):
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 20)
    assert kind_of(photo) == "photo"

    doc = tmp_path / "b.pdf"
    doc.write_bytes(b"%PDF-1.7\n")
    assert kind_of(doc) == "document"

    unknown = tmp_path / "c.bin"
    unknown.write_bytes(b"\x00\x01\x02\x03")
    assert kind_of(unknown) == "other"


def test_dedupe_prefers_metadata_recovery():
    carved = Artifact(id="a", recovered_path="x", sha256="same", recovery_method="carved")
    meta = Artifact(id="b", recovered_path="y", sha256="same", recovery_method="metadata")
    result = dedupe([carved, meta])
    assert len(result) == 1
    assert result[0].recovery_method == "metadata"
