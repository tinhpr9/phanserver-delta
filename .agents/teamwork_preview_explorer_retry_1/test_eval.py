import re

test_cases = [
    # (input_string, expected_valid_ip_or_None)
    ("CONNECTED: 100.80.175.55", "100.80.175.55"),
    ("CONNECTED: 100.64.0.1", "100.64.0.1"),
    ("CONNECTED: 100.127.255.254", "100.127.255.254"),
    ("CONNECTED: 100.0.0.0", "100.0.0.0"),
    ("CONNECTED: 100.255.255.255", "100.255.255.255"),
    ("CONNECTED: 100.100.100.100", "100.100.100.100"),
    ("CONNECTED: 100.80.175.55\n", "100.80.175.55"),
    ("IP is 100.80.175.55 on tun0", "100.80.175.55"),
    ("(100.80.175.55)", "100.80.175.55"),
    # Malformed cases that must be REJECTED:
    ("CONNECTED: 100.300.1.1", None),
    ("CONNECTED: 100.1.256.1", None),
    ("CONNECTED: 100.1.1.999", None),
    ("CONNECTED: 100.1.2.2555", None),
    ("CONNECTED: 1100.1.2.3", None),
    ("CONNECTED: 100.1.2.3.4", None),
    ("CONNECTED: .100.1.2.3", None),
    ("CONNECTED: 100.1.2.", None),
    ("CONNECTED: 100..1.2", None),
    ("100.abc.1.1", None),
    ("100.1.1", None),
    ("TRIGGERED", None),
    ("", None),
]

def eval_A(text):
    if not text: return None
    m = re.search(r"\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", text)
    if not m: return None
    octs = [int(g) for g in m.groups()]
    if any(o > 255 for o in octs): return None
    return m.group(0)

def eval_B(text):
    if not text: return None
    m = re.search(r"(?<![\d.])\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b(?![\d.])", text)
    if not m: return None
    octs = [int(g) for g in m.groups()]
    if any(o > 255 for o in octs): return None
    return m.group(0)

print(f"{'Input':35} | {'Expected':15} | {'Pattern A':16} | {'Pattern B':16}")
print("-" * 88)
for text, expected in test_cases:
    res_A = eval_A(text)
    res_B = eval_B(text)
    match_A = "OK" if res_A == expected else f"FAIL({res_A})"
    match_B = "OK" if res_B == expected else f"FAIL({res_B})"
    print(f"{repr(text):35} | {repr(expected):15} | {match_A:16} | {match_B:16}")
