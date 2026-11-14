"""Seeded, deterministic benchmark data: N rows x 20 columns, a second table for joins."""
from __future__ import annotations

import datetime as dt
import random

import polars as pl

PERSIAN_FIRST = ["علی", "سارا", "محمد", "مریم", "حسین", "زهرا", "رضا", "فاطمه", "امیر", "نرگس", "کیان", "یاسمن"]
PERSIAN_LAST = ["رضایی", "احمدی", "کریمی", "موسوی", "حسینی", "نوری", "کاظمی", "صادقی", "گل‌محمدی", "می‌خواهم"]
CITIES = ["تهران", "کرج", "قم", "شیراز", "اصفهان", "تبریز", "مشهد", "یزد"]
PD = "۰۱۲۳۴۵۶۷۸۹"


def _persian_digits(n: int) -> str:
    return "".join("٬" if c == "," else PD[int(c)] for c in f"{n:,}")  # Persian digits, thousands separator "٬"


def generate(rows: int, seed: int = 20261113) -> pl.DataFrame:
    r = random.Random(seed)
    base = dt.date(2015, 1, 1)

    def nullable(v, p=0.1):  # type: ignore[no-untyped-def]
        return None if r.random() < p else v

    def name() -> str:
        s = f"{r.choice(PERSIAN_FIRST)} {r.choice(PERSIAN_LAST)}"
        return s.replace("ی", "ي") if r.random() < 0.1 else (s.replace("ک", "ك") if r.random() < 0.1 else s)

    n_unique = int(rows * 0.9)
    cols: dict[str, list] = {k: [] for k in (  # type: ignore[type-arg]
        "id", "key", "group8", "qty", "price", "score", "ratio", "active", "created", "updated", "ts",
        "name", "city", "note", "email", "code", "amount_text", "jalali_text", "tags", "flag")}
    for i in range(n_unique):
        d = base + dt.timedelta(days=r.randint(0, 3650))
        cols["id"].append(i)
        cols["key"].append(f"k{r.randint(0, rows // 10):06d}")
        cols["group8"].append(r.choice(CITIES))
        cols["qty"].append(nullable(r.randint(1, 100)))
        cols["price"].append(nullable(round(r.random() * 1000, 2)))
        cols["score"].append(nullable(round(r.gauss(50, 15), 3)))
        cols["ratio"].append(nullable(r.random()))
        cols["active"].append(nullable(r.random() < 0.5))
        cols["created"].append(nullable(d))
        cols["updated"].append(nullable(d + dt.timedelta(days=r.randint(0, 400))))
        cols["ts"].append(nullable(dt.datetime(d.year, d.month, d.day, r.randint(0, 23), r.randint(0, 59), r.randint(0, 59))))
        cols["name"].append(nullable(name()))
        cols["city"].append(nullable(r.choice(CITIES)))
        cols["note"].append(nullable(f"  توضیح {r.randint(0, 999)}   متن ـ نمونه  "))
        cols["email"].append(nullable(f"User{r.randint(0, 99999)}@Example.com"))
        cols["code"].append(f"A{r.randint(0, 999):03d}-{r.randint(0, 99):02d}")
        cols["amount_text"].append(nullable(_persian_digits(r.randint(1000, 99_999_999))))
        cols["jalali_text"].append(nullable(f"{r.randint(1380, 1403)}/{r.randint(1, 12):02d}/{r.randint(1, 29):02d}"))
        cols["tags"].append(nullable(",".join(r.sample(["الف", "ب", "پ", "ت", "ث"], r.randint(1, 4)))))
        cols["flag"].append(r.choice(["بله", "خیر", "yes", "no"]))
    df = pl.DataFrame(cols, schema_overrides={"ts": pl.Datetime("us"), "created": pl.Date, "updated": pl.Date})
    dup = df.sample(n=rows - n_unique, with_replacement=True, seed=seed)  # ~10% exact duplicate rows
    return pl.concat([df, dup]).sample(fraction=1.0, shuffle=True, seed=seed)


def generate_right(rows: int, seed: int = 7) -> pl.DataFrame:
    r = random.Random(seed)
    keys = [f"k{n:06d}" for n in range(rows // 10 + 1)]
    return pl.DataFrame({"key": keys, "region": [r.choice(CITIES) for _ in keys], "weight": [round(r.random(), 4) for _ in keys]})
