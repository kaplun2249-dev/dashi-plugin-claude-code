#!/usr/bin/env python3
"""Разбор Excel-выгрузок из Bider в CSV, которые читает агент.

Колонки Bider заранее не известны и меняются от вкладки к вкладке, поэтому
скрипт не угадывает схему: он находит строку заголовков, показывает, что нашёл,
и складывает данные как есть. Приведение к своим названиям — задача агента,
который читает CSV вместе с profile.md кабинета.

    python3 scripts/bider-ingest.py --input export.xlsx --account own --inspect
    python3 scripts/bider-ingest.py --input export.xlsx --account own

Зависимость: openpyxl (pip install openpyxl).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit("нужен openpyxl: pip install openpyxl")

# Сколько верхних строк просматриваем в поисках заголовков. Выгрузки обычно
# начинаются с названия отчёта и периода, поэтому не первая строка.
HEADER_SCAN_ROWS = 15


def slugify(name: str) -> str:
    """Имя листа → безопасное имя файла. Кириллица сохраняется."""
    s = re.sub(r"[^\w\-]+", "-", (name or "").strip(), flags=re.UNICODE)
    return s.strip("-").lower() or "sheet"


def find_header_row(rows: list[list], scan: int = HEADER_SCAN_ROWS) -> int:
    """Индекс строки заголовков: больше всего непустых ячеек, и под ней есть данные.

    Возвращает 0, если ничего похожего не нашлось — тогда лист пишется как есть.
    """
    best_idx, best_filled = 0, 0
    for i, row in enumerate(rows[:scan]):
        filled = sum(1 for c in row if c is not None and str(c).strip())
        has_data_below = any(
            any(c is not None and str(c).strip() for c in r) for r in rows[i + 1 : i + 4]
        )
        if filled > best_filled and has_data_below:
            best_idx, best_filled = i, filled
    return best_idx


def read_sheet(ws) -> list[list]:
    return [list(r) for r in ws.iter_rows(values_only=True)]


def trim_trailing_empty(rows: list[list]) -> list[list]:
    while rows and not any(c is not None and str(c).strip() for c in rows[-1]):
        rows.pop()
    return rows


def cell_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()[:10] if isinstance(value, dt.date) else value.isoformat()
    return str(value)


def main() -> int:
    ap = argparse.ArgumentParser(description="Разбор выгрузок Bider в CSV")
    ap.add_argument("--input", required=True, type=Path, help="файл .xlsx из Bider")
    ap.add_argument("--account", default="own", help="slug кабинета (каталог в data/)")
    ap.add_argument("--lab-root", type=Path, default=Path.home() / ".claude-lab")
    ap.add_argument("--agent", default="nomado-market")
    ap.add_argument("--sheet", action="append", help="только эти листы (можно несколько)")
    ap.add_argument("--header-row", type=int, help="номер строки заголовков (с 1), если автопоиск ошибся")
    ap.add_argument("--inspect", action="store_true", help="показать структуру и выйти")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.input.exists():
        sys.exit(f"файл не найден: {args.input}")

    wb = load_workbook(args.input, read_only=True, data_only=True)
    out_dir = args.lab_root / args.agent / ".claude" / "data" / args.account
    stamp = dt.date.today().isoformat()

    print(f"Bider ingest · {args.input.name}")
    print(f"  кабинет:  {args.account}")
    if not args.inspect:
        print(f"  назначение: {out_dir}")
    print()

    written = []
    for ws in wb.worksheets:
        if args.sheet and ws.title not in args.sheet:
            continue

        rows = trim_trailing_empty(read_sheet(ws))
        if not rows:
            print(f"  — {ws.title}: пусто, пропуск")
            continue

        hdr = args.header_row - 1 if args.header_row else find_header_row(rows)
        headers = [cell_to_text(c) for c in rows[hdr]]
        data = rows[hdr + 1 :]
        # Строки-разделители и итоговые пустышки в выгрузках — обычное дело.
        data = [r for r in data if any(c is not None and str(c).strip() for c in r)]

        print(f"  — {ws.title}: заголовки в строке {hdr + 1}, данных {len(data)}")
        if args.inspect:
            shown = [h for h in headers if h][:12]
            print(f"      колонки: {', '.join(shown)}"
                  + (f" … ещё {len([h for h in headers if h]) - len(shown)}"
                     if len([h for h in headers if h]) > len(shown) else ""))
            continue

        dst = out_dir / f"{slugify(ws.title)}-{stamp}.csv"
        if args.dry_run:
            print(f"      [dry-run] → {dst.name}")
            written.append((ws.title, dst, len(data)))
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(headers)
            for r in data:
                w.writerow([cell_to_text(c) for c in r])
        print(f"      → {dst.name}")
        written.append((ws.title, dst, len(data)))

    if args.inspect:
        print("\nЕсли строка заголовков определена неверно — передайте --header-row N.")
        return 0

    if not written:
        print("\nНичего не записано.")
        return 1

    if not args.dry_run:
        index = out_dir / "README.md"
        with index.open("w", encoding="utf-8") as fh:
            fh.write(f"# Выгрузки Bider · кабинет `{args.account}`\n\n")
            fh.write(f"Последний импорт: {stamp}, источник `{args.input.name}`.\n\n")
            fh.write("| Лист | Файл | Строк |\n|---|---|---|\n")
            for title, dst, n in written:
                fh.write(f"| {title} | `{dst.name}` | {n} |\n")
            fh.write("\nСтарые выгрузки не удаляются: по ним видна динамика.\n")
        print(f"\nИндекс: {index}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
