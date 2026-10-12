import difflib
import json
from pathlib import Path


def get_chrome_profiles() -> dict:
    local_state_path = Path.home() / ".config/google-chrome/Local State"
    if not local_state_path.is_file():
        return {}
    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        return data.get("profile", {}).get("info_cache", {})
    except Exception:
        return {}


def find_chrome_profile_for_account(account: str, profiles: dict | None = None) -> str | None:
    profs = profiles if profiles is not None else get_chrome_profiles()
    if not profs:
        return None

    clean_acc = account.lower().replace("@gmail.com", "").strip()
    norm = lambda s: s.replace("kh", "ch").replace("k", "ch")
    norm_target = norm(clean_acc)

    # 1. Exact match on username or email prefix
    for prof_dir, info in profs.items():
        uname = (info.get("user_name") or info.get("email") or "").strip().lower()
        if uname and (clean_acc == uname.split("@")[0] or norm_target == norm(uname.split("@")[0])):
            return prof_dir

    # 2. Substring match
    for prof_dir, info in profs.items():
        uname = (info.get("user_name") or info.get("email") or "").strip().lower()
        if uname:
            prefix = uname.split("@")[0]
            if clean_acc in prefix or prefix in clean_acc or norm_target in norm(prefix):
                return prof_dir

    # 3. Fuzzy similarity
    ranked = sorted(
        (
            (difflib.SequenceMatcher(None, norm_target, norm(uname.split("@")[0])).ratio(), prof_dir)
            for prof_dir, info in profs.items()
            if (uname := (info.get("user_name") or info.get("email") or "").strip().lower())
        ),
        reverse=True,
        key=lambda pair: pair[0],
        default=((0.0, None),),
    )
    best_score, best_prof = ranked[0]
    return best_prof if best_score >= 0.7 else None
