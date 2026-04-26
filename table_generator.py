from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from product_matcher import MatchResult

_DISPENSARY_MENU_URL = (
    "https://shop.gardensdispensary.com"
    "/locations/cannabis-dispensary-garfield-nj/rec-menu/5713/menu"
)


def _post_age(post_date: datetime) -> str:
    delta = datetime.utcnow() - post_date
    days = delta.days
    if days == 0:
        hours = delta.seconds // 3600
        return f"{hours}h ago" if hours else "just now"
    if days == 1:
        return "1 day ago"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return f"{days // 7}w ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def _score_class(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "mid"
    return "low"


def _build_meta_html(reddit_config, posts_fetched: int, mentions_found: int) -> str:
    """Render the search-criteria summary block shown at the top of the report."""
    from config import RelativeDateRange, AbsoluteDateRange

    dr = reddit_config.date_range
    if isinstance(dr, RelativeDateRange):
        date_range_label = dr.value.replace("_", " ").title()
        cutoff = dr.to_cutoff().strftime("%Y-%m-%d")
        date_range_str = f"{date_range_label} (since {cutoff})"
    elif isinstance(dr, AbsoluteDateRange):
        date_range_str = f"{dr.start.strftime('%Y-%m-%d')} to {dr.end.strftime('%Y-%m-%d')}"
    else:
        date_range_str = "Unknown"

    subreddit_items = "".join(
        f"<li><strong>r/{s.name}</strong> &mdash; "
        f"keywords: {', '.join(f'&ldquo;{t}&rdquo;' for t in s.topics)}</li>"
        for s in reddit_config.subreddits
    )
    matched = sum(1 for m in [])  # placeholder; actual count appended by caller

    return f"""<div class="meta">
  <div class="meta-grid">
    <div class="meta-item"><span class="meta-label">Time frame</span><span class="meta-value">{date_range_str}</span></div>
    <div class="meta-item"><span class="meta-label">Posts analysed</span><span class="meta-value">{posts_fetched}</span></div>
    <div class="meta-item"><span class="meta-label">Positive mentions found</span><span class="meta-value">{mentions_found}</span></div>
    <div class="meta-item"><span class="meta-label">Max posts / keyword</span><span class="meta-value">{reddit_config.max_posts_per_topic}</span></div>
  </div>
  <div class="meta-subs">
    <span class="meta-label">Subreddits &amp; keywords</span>
    <ul>{subreddit_items}</ul>
  </div>
</div>"""


def generate_match_table_html(
    matches: List[MatchResult],
    project_name: str,
    reddit_config=None,
    posts_fetched: int = 0,
) -> str:
    rows_html = _build_rows(matches)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    matched_count = sum(1 for m in matches if m.dispensary_product)
    meta_html = (
        _build_meta_html(reddit_config, posts_fetched, len(matches))
        if reddit_config is not None else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{project_name} — Product Match Table</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 1.5rem 2rem; color: #1a1a1a; background: #f8f9f8;
  }}
  h1 {{ font-size: 1.3rem; margin-bottom: 0.25rem; color: #1a3d1a; }}
  .subtitle {{ color: #555; font-size: 0.85rem; margin-bottom: 1rem; }}
  .subtitle a {{ color: #2d6a2d; }}

  /* Metadata block */
  .meta {{
    background: #fff; border: 1px solid #d4e6d4; border-radius: 8px;
    padding: 1rem 1.2rem; margin-bottom: 1.5rem; font-size: 0.85rem;
  }}
  .meta-grid {{
    display: flex; flex-wrap: wrap; gap: 1rem 2rem; margin-bottom: 0.75rem;
  }}
  .meta-item {{ display: flex; flex-direction: column; }}
  .meta-label {{ font-weight: 600; color: #2d6a2d; font-size: 0.75rem;
                 text-transform: uppercase; letter-spacing: 0.04em; }}
  .meta-value {{ color: #222; margin-top: 2px; }}
  .meta-subs ul {{ margin: 0.35rem 0 0 1.2rem; padding: 0; color: #333; }}
  .meta-subs li {{ margin-bottom: 0.2rem; }}

  /* Table */
  table {{ border-collapse: collapse; width: 100%; font-size: 0.875rem;
           background: #fff; border-radius: 8px; overflow: hidden;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  thead tr {{ background: #2d6a2d; color: #fff; }}
  th {{ padding: 0.65rem 0.9rem; text-align: left; font-weight: 600;
        white-space: nowrap; }}
  td {{ padding: 0.55rem 0.9rem; border-bottom: 1px solid #eaeeea;
        vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: #f2f7f2; }}
  a {{ color: #2d6a2d; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .brand {{ color: #555; font-size: 0.8rem; display: block; margin-top: 2px; }}
  .kind-badge {{
    display: inline-block; font-size: 0.72rem; font-weight: 600;
    padding: 2px 7px; border-radius: 20px;
    background: #e8f3e8; color: #2d6a2d; white-space: nowrap;
  }}
  .note {{ color: #444; font-size: 0.82rem; font-style: italic; }}
  .score {{ font-weight: 700; font-size: 0.85rem; }}
  .score.high {{ color: #1a7a1a; }}
  .score.mid  {{ color: #b87e00; }}
  .score.low  {{ color: #999; }}
  .no-match {{ color: #999; font-style: italic; }}
  .age {{ white-space: nowrap; color: #666; font-size: 0.82rem; }}
  .thread-link {{ font-size: 0.82rem; }}
</style>
</head>
<body>
<h1>{project_name} — Reddit &times; Dispensary Match</h1>
<p class="subtitle">
  Products positively mentioned on Reddit matched against the live menu at
  <a href="{_DISPENSARY_MENU_URL}" target="_blank">Gardens Dispensary Garfield (rec)</a>.
  Generated {now} UTC &mdash; {matched_count}/{len(matches)} mentions in stock.
</p>
{meta_html}
<table>
  <thead>
    <tr>
      <th>Reddit Mention</th>
      <th>Type</th>
      <th>Why People Love It</th>
      <th>Garfield Garden Product (click)</th>
      <th>Product Match Score</th>
      <th>Reddit Thread (click)</th>
      <th>Post Age</th>
    </tr>
  </thead>
  <tbody>
{rows_html}  </tbody>
</table>
</body>
</html>
"""


def _build_rows(matches: List[MatchResult]) -> str:
    if not matches:
        return '    <tr><td colspan="7" style="text-align:center;padding:2rem;color:#999;">No product mentions found.</td></tr>\n'

    lines = []
    for m in matches:
        mention_html = (
            f"<strong>{m.mention.name}</strong>"
            f'<span class="brand">{m.mention.brand}</span>'
        )
        kind_html = (
            f'<span class="kind-badge">{m.mention.kind}</span>'
            if m.mention.kind else "&mdash;"
        )
        note_html = (
            f'<span class="note">{m.mention.note}</span>'
            if m.mention.note else "&mdash;"
        )

        if m.dispensary_product:
            dp = m.dispensary_product
            match_html = (
                f'<a href="{dp.url}" target="_blank">{dp.name}</a>'
                f'<span class="brand">{dp.brand}</span>'
            )
            sc = _score_class(m.composite_score)
            score_html = f'<span class="score {sc}">{m.composite_score:.0f}%</span>'
        else:
            match_html = '<span class="no-match">No match found</span>'
            score_html = '<span class="score low">&mdash;</span>'

        thread_html = f'<a class="thread-link" href="{m.mention.source_url}" target="_blank">&#8599; thread</a>'
        age = _post_age(m.mention.source_date)
        post_date = m.mention.source_date.strftime("%Y-%m-%d")

        lines.append(
            f"    <tr>\n"
            f"      <td>{mention_html}</td>\n"
            f"      <td>{kind_html}</td>\n"
            f"      <td>{note_html}</td>\n"
            f"      <td>{match_html}</td>\n"
            f"      <td>{score_html}</td>\n"
            f"      <td>{thread_html}</td>\n"
            f'      <td class="age" title="{post_date}">{age}</td>\n'
            f"    </tr>\n"
        )
    return "".join(lines)
