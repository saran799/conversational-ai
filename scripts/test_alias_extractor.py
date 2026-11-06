import sys
sys.path.insert(0, ".")
import csv
import os
import re

_KNOWN_ALIASES = set()
alias_path = "data/curated/stop_aliases.csv"
if os.path.exists(alias_path):
    with open(alias_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") == "approved":
                a = row.get("alias", "").strip().lower()
                if a:
                    _KNOWN_ALIASES.add(a)

print("Loaded aliases:", len(_KNOWN_ALIASES))

def extract_spots_from_phrase(clean: str):
    clean_norm = re.sub(r"[?,.!;:()]+", " ", clean).strip()
    words = clean_norm.split()
    matched = []
    i = 0
    while i < len(words):
        # try 3-word, 2-word, 1-word
        if i + 2 < len(words):
            three = f"{words[i]} {words[i+1]} {words[i+2]}".lower()
            if three in _KNOWN_ALIASES:
                matched.append(three)
                i += 3
                continue
        if i + 1 < len(words):
            two = f"{words[i]} {words[i+1]}".lower()
            if two in _KNOWN_ALIASES:
                matched.append(two)
                i += 2
                continue
        one = words[i].lower()
        clean_w = re.sub(r"(?:யில்|யில|இல்|ில்|லிருந்து|இருந்து|லெருந்து|க்கு|கு)$", "", one)
        if clean_w.endswith("ர"): clean_w = clean_w[:-1] + "ர்"
        elif clean_w.endswith("ய"): clean_w = clean_w[:-1]
        if clean_w in _KNOWN_ALIASES:
            matched.append(clean_w)
        i += 1
    return matched

print("1.", extract_spots_from_phrase("ஆவடி கந்த பூந்தமல்லி போனோம்"))
print("2.", extract_spots_from_phrase("போரூரில் இருந்து கிண்டிக்கு செல்ல வேண்டும்"))
print("3.", extract_spots_from_phrase("avadi poonamalle"))
print("4.", extract_spots_from_phrase("porur to guindy"))

