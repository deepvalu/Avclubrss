"""Build feed.xml (RSS 2.0) from weeks.json. Newest week first."""
import json, datetime
from xml.sax.saxutils import escape
from email.utils import format_datetime

weeks = json.load(open("weeks.json"))
weeks.sort(key=lambda w: w["start"], reverse=True)

def rfc822(d):
    dt = datetime.datetime.fromisoformat(d).replace(hour=11, tzinfo=datetime.timezone.utc)
    return format_datetime(dt)

items = []
for w in weeks:
    html = "<ul>" + "".join(f"<li>{escape(p)}</li>" for p in w["picks"]) + "</ul>"
    html += f'<p><a href="{escape(w["url"])}">Read the full A.V. Club column</a></p>'
    items.append(f"""  <item>
    <title>{escape("A.V. Club picks: " + w["label"] + ", " + w["start"][:4])}</title>
    <link>{escape(w["url"])}</link>
    <guid isPermaLink="false">avclub-whats-on-{w["start"]}</guid>
    <pubDate>{rfc822(w["start"])}</pubDate>
    <description><![CDATA[{html}]]></description>
  </item>""")

now = format_datetime(datetime.datetime.now(datetime.timezone.utc))
feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>A.V. Club What's On – Weekly TV Picks</title>
  <link>https://www.avclub.com/tv</link>
  <description>The headline shows from The A.V. Club's weekly "What's On" TV column, one item per week.</description>
  <language>en-us</language>
  <lastBuildDate>{now}</lastBuildDate>
  <ttl>1440</ttl>
{chr(10).join(items)}
</channel>
</rss>
"""
open("feed.xml", "w").write(feed)
print(f"{len(weeks)} items written")
