import io
from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, create_engine, text
from sqlalchemy.orm import Session, declarative_base

from leventum.db.base import Money
from leventum.storage import FileValidationError, LocalFileStore

B = declarative_base()


class T(B):
    __tablename__ = "t"
    id = Column(Integer, primary_key=True)
    amt = Column(Money)


def test_money_roundtrip_is_exact_and_stored_as_integer_cents():
    e = create_engine("sqlite://")
    B.metadata.create_all(e)
    with Session(e) as s:
        s.add(T(amt=Decimal("1150.10")))
        s.add(T(amt=Decimal("0.07")))
        s.commit()
        assert s.query(T).order_by(T.id).all()[0].amt == Decimal("1150.10")
        assert [r[0] for r in s.execute(text("select amt from t order by id"))] == [115010, 7]
        # klassische float-Falle: 0.1+0.2
        s.add(T(amt=Decimal("0.1") + Decimal("0.2")))
        s.commit()
        assert s.query(T).all()[-1].amt == Decimal("0.30")


def test_money_rejects_sub_cent():
    e = create_engine("sqlite://")
    B.metadata.create_all(e)
    with Session(e) as s:
        s.add(T(amt=Decimal("1.005")))
        with pytest.raises(Exception):
            s.commit()


@pytest.fixture
def store(tmp_path):
    return LocalFileStore(tmp_path / "docs", max_bytes=1024)


def test_store_saves_with_random_key_and_hash(store):
    f = store.save(io.BytesIO(b"%PDF-1.4 hello"), "Mietvertrag Müller.pdf")
    assert f.mime == "application/pdf" and f.size == 14 and len(f.sha256) == 64
    assert "Mietvertrag" not in f.key and not f.key.startswith("/")
    assert store.open(f.key).read() == b"%PDF-1.4 hello"
    store.delete(f.key)
    assert not store.exists(f.key)


@pytest.mark.parametrize("name,data", [
    ("evil.exe", b"MZ..."), ("noext", b"abc"), ("fake.pdf", b"not a pdf"), ("empty.pdf", b""),
    ("big.pdf", b"%PDF-" + b"x" * 2000)])
def test_store_rejects_bad_files_and_leaves_no_residue(store, name, data, tmp_path):
    with pytest.raises(FileValidationError):
        store.save(io.BytesIO(data), name)
    assert [p for p in (tmp_path / "docs").rglob("*") if p.is_file()] == []


def test_store_blocks_path_traversal(store):
    with pytest.raises(FileValidationError):
        store.open("../../etc/passwd")
    with pytest.raises(FileValidationError):
        store.delete("../x")


def test_original_name_path_stripped(store):
    f = store.save(io.BytesIO(b"%PDF-1"), "..\\..\\secret\\a.pdf")
    assert f.original_name == "a.pdf"
