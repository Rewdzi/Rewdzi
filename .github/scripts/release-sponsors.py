"""Daily: put the current monthly sponsors into every release note of the owner's own repos (no forks).
One-time sponsors ($50+) are added for good to the first release published after they paid.
Needs SPONSORS_TOKEN (reads sponsors) and RELEASES_TOKEN (edits releases in all repos)."""
import json, os, re, subprocess, sys

START, END = "<!-- sponsors-start -->", "<!-- sponsors-end -->"
SPONSOR_PAGE = "https://github.com/sponsors/Rewdzi"
PLACEHOLDER = "https://github.com/Rewdzi/Rewdzi/raw/main/assets/your-photo-here.svg"

# shortcut: reads the first 100 sponsorships only, add paging if that ever runs out
QUERY = """{ viewer { sponsorshipsAsMaintainer(first: 100, activeOnly: false) { nodes {
  createdAt isActive isOneTimePayment privacyLevel tier { monthlyPriceInCents }
  sponsorEntity { ... on User { login avatarUrl } ... on Organization { login avatarUrl } } } } } }"""


def gh(token, *args):
    env = dict(os.environ, GH_TOKEN=token)
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, env=env).stdout


def pic(s, width):
    return f'<a href="https://github.com/{s["login"]}"><img src="{s["avatarUrl"]}" width="{width}px" alt="{s["login"]}" /></a>'


def section(top, monthly, one_time):
    lines = [START, "### Sponsors", f"[Become a sponsor]({SPONSOR_PAGE}) and your profile picture is featured here.", ""]
    if top:
        lines += [" ".join(pic(s, 80) for s in top), ""]
    lines += [" ".join([pic(s, 60) for s in monthly] + [
        f'<a href="{SPONSOR_PAGE}"><img src="{PLACEHOLDER}" width="60px" alt="Your logo, brand or photo here?" /></a>']), ""]
    if one_time:
        lines += ["**This release was sponsored by**", "", " ".join(pic(s, 60) for s in one_time), ""]
    return "\n".join(lines + [END])


def merge(body, sec):
    body = body or ""
    if START in body and END in body:
        return re.sub(re.escape(START) + ".*?" + re.escape(END), lambda m: sec, body, flags=re.S)
    return (body.rstrip() + "\n\n" + sec).lstrip()


def main():
    sponsors_token, releases_token = os.environ.get("SPONSORS_TOKEN"), os.environ.get("RELEASES_TOKEN")
    if not sponsors_token or not releases_token:
        print("::warning::SPONSORS_TOKEN or RELEASES_TOKEN secret missing, release notes not updated")
        return

    nodes = json.loads(gh(sponsors_token, "api", "graphql", "-f", f"query={QUERY}"))["data"]["viewer"]["sponsorshipsAsMaintainer"]["nodes"]
    nodes = [n for n in nodes if n["privacyLevel"] == "PUBLIC" and n["sponsorEntity"]]
    cents = lambda n: n["tier"]["monthlyPriceInCents"]
    monthly = [n for n in nodes if n["isActive"] and not n["isOneTimePayment"] and cents(n) >= 2500]
    top = [n["sponsorEntity"] for n in monthly if cents(n) >= 10000]
    rest = [n["sponsorEntity"] for n in monthly if cents(n) < 10000]
    one_time = [n for n in nodes if n["isOneTimePayment"] and cents(n) >= 5000]

    # --source = the owner's own repos only, forks skipped
    repos = json.loads(gh(releases_token, "repo", "list", "Rewdzi", "--source", "--limit", "1000", "--json", "nameWithOwner,isArchived"))
    releases = []
    for r in repos:
        if r["isArchived"]:
            continue  # archived repos are read-only
        pages = json.loads(gh(releases_token, "api", f"repos/{r['nameWithOwner']}/releases", "--paginate", "--slurp"))
        releases += [dict(rel, repo=r["nameWithOwner"]) for page in pages for rel in page if rel.get("published_at")]
    releases.sort(key=lambda rel: rel["published_at"])

    # each one-time sponsor belongs to the first release (any repo) published after they paid
    owed = {}
    for n in one_time:
        first = next((rel for rel in releases if rel["published_at"] > n["createdAt"]), None)
        if first:
            owed.setdefault(first["id"], []).append(n["sponsorEntity"])

    for rel in releases:
        body = merge(rel["body"], section(top, rest, owed.get(rel["id"], [])))
        if body != (rel["body"] or ""):
            gh(releases_token, "api", "-X", "PATCH", f"repos/{rel['repo']}/releases/{rel['id']}", "-f", f"body={body}")
            print(f"updated {rel['repo']} {rel['tag_name']}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        a = {"login": "a", "avatarUrl": "https://x/a"}
        sec = section([a], [], [a])
        once = merge("Notes", sec)
        assert once.startswith("Notes\n\n" + START) and once.count(START) == 1
        assert merge(once, sec) == once, "second run must change nothing"
        assert merge(once, section([], [], [])).count('src="https://x/a"') == 0, "old sponsor removed"
        assert merge(None, sec) == sec
        print("ok")
    else:
        main()
