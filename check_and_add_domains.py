#!/usr/bin/env python3
"""
Скрипт для перевірки дублікатів та додавання/видалення доменів у файли блокування.

Підтримувані формати:
  - MikroTik hosts:  0.0.0.0 domain.com
  - Unbound DNS:     local-zone: "domain.com" always_nxdomain

КОМАНДИ:

  1. Перевірка внутрішніх дублікатів у файлах:
     python check_and_add_domains.py --check domains_mikrotik.txt domains_unbound.txt

  2. Перевірка — чи є домени з new_domains.txt у файлах блокування (без змін):
     python check_and_add_domains.py --check-file new_domains.txt --mikrotik domains_mikrotik.txt --unbound domains_unbound.txt

  3. Додати домени з new_domains.txt в обидва файли:
     python check_and_add_domains.py --add-file new_domains.txt --mikrotik domains_mikrotik.txt --unbound domains_unbound.txt

  4. Видалити домени з new_domains.txt з обох файлів:
     python check_and_add_domains.py --remove-file new_domains.txt --mikrotik domains_mikrotik.txt --unbound domains_unbound.txt

  5. Додати/видалити домени вручну (через пробіл):
     python check_and_add_domains.py --add evil.com spam.ru --mikrotik domains_mikrotik.txt --unbound domains_unbound.txt
     python check_and_add_domains.py --remove evil.com spam.ru --mikrotik domains_mikrotik.txt --unbound domains_unbound.txt

  6. Попередній перегляд без змін — додай --dry-run до будь-якої команди:
     python check_and_add_domains.py --add-file new_domains.txt --mikrotik domains_mikrotik.txt --unbound domains_unbound.txt --dry-run
"""

import argparse
import sys
import re
from pathlib import Path


# ──────────────────────────────────────────────
# Парсинг форматів
# ──────────────────────────────────────────────

def detect_format(filepath: Path) -> str:
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("local-zone:"):
                return "unbound"
            if re.match(r"^0\.0\.0\.0\s+\S+", line):
                return "mikrotik"
    raise ValueError(f"Не вдалося визначити формат файлу: {filepath}")


def parse_domain_mikrotik(line: str) -> str | None:
    m = re.match(r"^0\.0\.0\.0\s+(\S+)", line.strip())
    return m.group(1).lower() if m else None


def parse_domain_unbound(line: str) -> str | None:
    m = re.match(r'^local-zone:\s+"([^"]+)"\s+always_nxdomain', line.strip())
    return m.group(1).lower() if m else None


def format_mikrotik(domain: str) -> str:
    return f"0.0.0.0 {domain}"


def format_unbound(domain: str) -> str:
    return f'local-zone: "{domain}" always_nxdomain'


PARSERS = {
    "mikrotik": parse_domain_mikrotik,
    "unbound":  parse_domain_unbound,
}

FORMATTERS = {
    "mikrotik": format_mikrotik,
    "unbound":  format_unbound,
}


# ──────────────────────────────────────────────
# Допоміжні функції
# ──────────────────────────────────────────────

def load_domains(filepath: Path, fmt: str) -> tuple[list[str], dict[str, int]]:
    parser = PARSERS[fmt]
    lines: list[str] = []
    index: dict[str, int] = {}
    with open(filepath, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            lines.append(raw.rstrip("\n"))
            domain = parser(raw)
            if domain and domain not in index:
                index[domain] = lineno
    return lines, index


def read_plain_domains(filepath: Path) -> list[str]:
    """Читає простий список доменів (по одному на рядок, # — коментар)."""
    with open(filepath, encoding="utf-8") as f:
        return [l.strip().lower() for l in f if l.strip() and not l.strip().startswith("#")]


def require_both_files(args) -> tuple[Path, Path]:
    if not args.mikrotik or not args.unbound:
        sys.exit("Вкажіть обидва файли: --mikrotik FILE --unbound FILE")
    mt, ub = Path(args.mikrotik), Path(args.unbound)
    for p in (mt, ub):
        if not p.exists():
            sys.exit(f"Файл не знайдено: {p}")
    return mt, ub


# ──────────────────────────────────────────────
# Основні функції
# ──────────────────────────────────────────────

def check_duplicates(filepath: Path) -> None:
    """Перевіряє файл на внутрішні дублікати."""
    fmt = detect_format(filepath)
    parser = PARSERS[fmt]
    seen: dict[str, int] = {}
    duplicates: list[tuple[int, str, int]] = []

    with open(filepath, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            domain = parser(raw)
            if not domain:
                continue
            if domain in seen:
                duplicates.append((lineno, domain, seen[domain]))
            else:
                seen[domain] = lineno

    print(f"\nФайл:   {filepath}")
    print(f"Формат: {fmt}")
    print(f"Всього унікальних доменів: {len(seen)}")

    if not duplicates:
        print("✅  Дублікатів не знайдено.\n")
    else:
        print(f"⚠️   Знайдено дублікатів: {len(duplicates)}\n")
        print(f"{'Рядок':>7}  {'Домен':<45}  {'Перший раз у рядку'}")
        print("-" * 70)
        for lineno, domain, first in duplicates:
            print(f"{lineno:>7}  {domain:<45}  {first}")
        print()


def check_file_against(domains_file: Path, mikrotik: Path, unbound: Path) -> None:
    """Перевіряє які домени з файлу вже є / відсутні у файлах блокування."""
    new_domains = read_plain_domains(domains_file)
    if not new_domains:
        sys.exit(f"Файл {domains_file} порожній або не містить доменів.")

    print(f"\n{'─'*55}")
    print(f"  Режим: перевірка  |  доменів у {domains_file.name}: {len(new_domains)}")
    print(f"{'─'*55}")

    for filepath in (mikrotik, unbound):
        fmt = detect_format(filepath)
        _, existing = load_domains(filepath, fmt)

        present  = [(d, existing[d]) for d in new_domains if d in existing]
        missing  = [d for d in new_domains if d not in existing]

        print(f"\n  📄 {filepath}  [{fmt}]")
        print(f"     Всього доменів у файлі: {len(existing)}")

        if present:
            print(f"\n     ✅  Вже присутні ({len(present)}) — додавати не потрібно:")
            for d, lineno in present:
                print(f"          рядок {lineno:>6}:  {d}")
        else:
            print(f"\n     ✅  Жодного зі списку ще немає у файлі.")

        if missing:
            print(f"\n     ➕  Відсутні ({len(missing)}) — можна додати:")
            for d in missing:
                print(f"          {d}")
        else:
            print(f"\n     ⏭️  Усі домени зі списку вже є у файлі.")

    print(f"\n{'─'*55}")
    print(f"  Файли НЕ змінено. Це лише перевірка.")
    print(f"{'─'*55}\n")


def add_domains_to_file(filepath: Path, new_domains: list[str], dry_run: bool) -> int:
    fmt = detect_format(filepath)
    _, existing = load_domains(filepath, fmt)
    formatter = FORMATTERS[fmt]

    to_add = []
    already_present = []

    for raw in new_domains:
        domain = raw.strip().lower()
        if not domain:
            continue
        if domain in existing:
            already_present.append((domain, existing[domain]))
        else:
            to_add.append(domain)

    print(f"\n  📄 {filepath}  [{fmt}]")

    if already_present:
        print(f"     ⏭️  Вже присутні ({len(already_present)}) — пропускаємо:")
        for d, lineno in already_present:
            print(f"          {d}  (рядок {lineno})")

    if not to_add:
        print("     ✅  Немає нових доменів для додавання.")
        return 0

    print(f"     ➕  Буде додано ({len(to_add)}):")
    for d in to_add:
        print(f"          {formatter(d)}")

    if not dry_run:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write("\n")
            for d in to_add:
                f.write(formatter(d) + "\n")
        print(f"     ✅  Записано.")

    return len(to_add)


def remove_domains_from_file(filepath: Path, targets: list[str], dry_run: bool) -> int:
    fmt = detect_format(filepath)
    parser = PARSERS[fmt]
    target_set = {d.strip().lower() for d in targets if d.strip()}

    new_lines = []
    removed = []

    with open(filepath, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            domain = parser(raw)
            if domain and domain in target_set:
                removed.append((lineno, raw.rstrip("\n")))
            else:
                new_lines.append(raw.rstrip("\n"))

    print(f"\n  📄 {filepath}  [{fmt}]")

    if not removed:
        print(f"     ℹ️  Жодного з вказаних доменів не знайдено у файлі.")
        return 0

    print(f"     🗑️  Буде видалено ({len(removed)}):")
    for lineno, line in removed:
        print(f"          рядок {lineno}: {line}")

    not_found = target_set - {parser(r) for _, r in removed}
    if not_found:
        print(f"     ℹ️  Не знайдено у файлі:")
        for d in sorted(not_found):
            print(f"          {d}")

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))
            if new_lines:
                f.write("\n")
        print(f"     ✅  Видалено.")

    return len(removed)


def process_both(
    mikrotik: Path,
    unbound: Path,
    domains: list[str],
    mode: str,
    dry_run: bool,
) -> None:
    label = "додавання" if mode == "add" else "видалення"
    tag   = "[dry-run] " if dry_run else ""
    print(f"\n{'─'*55}")
    print(f"  {tag}Режим: {label}  |  доменів: {len(domains)}")
    print(f"{'─'*55}")

    if mode == "add":
        n1 = add_domains_to_file(mikrotik, domains, dry_run)
        n2 = add_domains_to_file(unbound,  domains, dry_run)
        print(f"\n{'─'*55}")
        if dry_run:
            print(f"  [dry-run] Файли НЕ змінено. Прибери --dry-run щоб записати.")
        else:
            print(f"  Підсумок: додано {n1} → mikrotik,  {n2} → unbound")
    else:
        n1 = remove_domains_from_file(mikrotik, domains, dry_run)
        n2 = remove_domains_from_file(unbound,  domains, dry_run)
        print(f"\n{'─'*55}")
        if dry_run:
            print(f"  [dry-run] Файли НЕ змінено. Прибери --dry-run щоб записати.")
        else:
            print(f"  Підсумок: видалено {n1} рядків → mikrotik,  {n2} → unbound")

    print(f"{'─'*55}\n")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Перевірка дублікатів та керування доменами у файлах блокування.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--check",       nargs="+", metavar="FILE",
                            help="Перевірити файл(и) на внутрішні дублікати")
    mode_group.add_argument("--check-file",  metavar="FILE",
                            help="Перевірити які домени з FILE вже є/відсутні у --mikrotik та --unbound (без змін)")
    mode_group.add_argument("--add",         nargs="+", metavar="DOMAIN",
                            help="Додати домени вручну (через пробіл)")
    mode_group.add_argument("--add-file",    metavar="FILE",
                            help="Додати домени зі списку-файлу в обидва файли блокування")
    mode_group.add_argument("--remove",      nargs="+", metavar="DOMAIN",
                            help="Видалити домени вручну (через пробіл)")
    mode_group.add_argument("--remove-file", metavar="FILE",
                            help="Видалити домени зі списку-файлу з обох файлів блокування")

    parser.add_argument("--mikrotik", metavar="FILE", help="Шлях до файлу MikroTik hosts")
    parser.add_argument("--unbound",  metavar="FILE", help="Шлях до файлу Unbound DNS")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Показати зміни без запису у файл")

    args = parser.parse_args()

    # ── --check ──────────────────────────────
    if args.check:
        for fname in args.check:
            p = Path(fname)
            if not p.exists():
                sys.exit(f"Файл не знайдено: {p}")
            check_duplicates(p)
        return

    # ── --check-file ─────────────────────────
    if args.check_file:
        cf = Path(args.check_file)
        if not cf.exists():
            sys.exit(f"Файл не знайдено: {cf}")
        mt, ub = require_both_files(args)
        check_file_against(cf, mt, ub)
        return

    # ── --add / --add-file / --remove / --remove-file ──
    mt, ub = require_both_files(args)

    if args.add or args.add_file:
        domains = list(args.add) if args.add else []
        if args.add_file:
            af = Path(args.add_file)
            if not af.exists():
                sys.exit(f"Файл не знайдено: {af}")
            domains += read_plain_domains(af)
        domains = list(dict.fromkeys(d for d in domains if d.strip()))
        if not domains:
            sys.exit("Список доменів порожній.")
        process_both(mt, ub, domains, "add", args.dry_run)

    elif args.remove or args.remove_file:
        domains = list(args.remove) if args.remove else []
        if args.remove_file:
            rf = Path(args.remove_file)
            if not rf.exists():
                sys.exit(f"Файл не знайдено: {rf}")
            domains += read_plain_domains(rf)
        domains = list(dict.fromkeys(d for d in domains if d.strip()))
        if not domains:
            sys.exit("Список доменів порожній.")
        process_both(mt, ub, domains, "remove", args.dry_run)


if __name__ == "__main__":
    main()
