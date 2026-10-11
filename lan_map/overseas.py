"""Who is out there beyond the sea.

A walk out of the island ends at a number, and a number says nothing: 142.251.151.6 and
213.157.200.141 look alike, and one of them is somebody watching YouTube. There are two ways
to tell who is at the far end, and they are not equally sure.

The router resolved a name for most of them, and a name is a fact: whatever answers to
rr2.sn-h5bupjvh-ucnr.googlevideo.com is YouTube, wherever it happens to stand — in Google's
own network or in a cache at the provider next door, which is exactly where that one stood.
So names are asked first, and they are asked from the end: a house owns a domain and
everything under it.

What the router never resolved leaves nothing but the address, and an address is read by the
water it floats in. Blocks are bought, sold and re-let, so this is a guess by range and the map
says so out loud: not "Google" but "somewhere in Google". A house here is never a person and
never a page — only who keeps the machine that answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network
from typing import ClassVar


@dataclass(frozen=True)
class House:
    """A house beyond the sea: what it is called, the domains it answers to, the water it owns."""
    name: str
    #: Domain endings. A name that ends in one of these, at a dot, belongs to this house.
    names: tuple = ()
    #: Address ranges it is known to keep. A guess by range, and called one.
    blocks: tuple = ()


#: Named services first, then the houses that keep them. A service is worth telling apart from
#: its owner: "YouTube" is an answer to "where does this one go", and "Google" only half of one.
HOUSES: tuple = (
    House("YouTube", ("youtube.com", "youtu.be", "googlevideo.com", "ytimg.com", "ggpht.com",
                      "youtube-nocookie.com", "yt3.ggpht.com")),
    House("Gmail", ("gmail.com", "googlemail.com")),
    House("iCloud Private Relay", ("apple-dns.net", "mask.icloud.com")),
    House("WhatsApp", ("whatsapp.com", "whatsapp.net", "wa.me")),
    House("Instagram", ("instagram.com", "cdninstagram.com")),
    House("Telegram", ("telegram.org", "telegram.me", "t.me", "telesco.pe", "tdesktop.com"),
          ("149.154.160.0/20", "91.108.4.0/22", "91.108.8.0/22", "91.108.12.0/22",
           "91.108.16.0/22", "91.108.20.0/22", "91.108.56.0/22", "95.161.64.0/20")),
    House("Roblox", ("roblox.com", "rbxcdn.com"), ("128.116.0.0/16",)),
    House("Netflix", ("netflix.com", "nflxvideo.net", "nflximg.net", "nflxext.com")),
    House("Spotify", ("spotify.com", "scdn.co", "spotifycdn.com")),
    House("Twitch", ("twitch.tv", "ttvnw.net", "jtvnw.net")),
    House("TikTok", ("tiktok.com", "tiktokcdn.com", "tiktokv.com", "byteoversea.com")),
    House("Discord", ("discord.com", "discord.gg", "discordapp.com", "discordapp.net")),
    House("Reddit", ("reddit.com", "redd.it", "redditstatic.com", "redditmedia.com")),
    House("X (Twitter)", ("x.com", "twitter.com", "twimg.com", "t.co")),
    House("Pinterest", ("pinterest.com", "pinterest.ru", "pinimg.com")),
    House("AliExpress", ("aliexpress.com", "aliexpress.ru", "alicdn.com")),
    House("Ozon", ("ozon.ru", "ozon.com", "ozone.ru")),
    House("Wildberries", ("wildberries.ru", "wb.ru", "wbbasket.ru", "wbstatic.net")),
    House("Steam", ("steampowered.com", "steamcommunity.com", "steamstatic.com",
                    "steamcontent.com", "valve.net")),
    House("Wikipedia", ("wikipedia.org", "wikimedia.org")),
    House("GitHub", ("github.com", "github.io", "githubusercontent.com", "ghcr.io")),
    House("Dropbox", ("dropbox.com", "dropboxusercontent.com")),
    House("Zoom", ("zoom.us",)),
    House("Slack", ("slack.com", "slack-edge.com")),
    House("Signal", ("signal.org",)),
    House("1Password", ("1password.com", "1passwordservices.com", "b5.dev")),
    House("Claude", ("claude.ai", "anthropic.com")),
    House("OpenAI", ("openai.com", "chatgpt.com", "oaistatic.com")),
    House("Sentry", ("sentry.io", "ingest.sentry.io")),
    House("Docker", ("docker.com", "docker.io")),
    House("PyPI", ("pypi.org", "pythonhosted.org", "python.org")),
    House("Home Assistant", ("home-assistant.io", "nabucasa.com")),
    House("Synology", ("synology.com", "quickconnect.to")),
    House("MikroTik", ("mikrotik.com",)),
    House("the ntp pool", ("ntp.org",)),
    House("Yandex", ("yandex.ru", "yandex.net", "yandex.com", "yastatic.net", "ya.ru")),
    House("VK", ("vk.com", "vk.ru", "userapi.com", "vkuservideo.net", "mycdn.me")),
    House("Apple", ("apple.com", "icloud.com", "mzstatic.com", "cdn-apple.com",
                    "push-apple.com", "itunes.com", "apple-cloudkit.com", "aaplimg.com"),
          ("17.0.0.0/8",)),
    House("Google", ("google.com", "googleapis.com", "gstatic.com", "googleusercontent.com",
                     "1e100.net", "google-analytics.com", "doubleclick.net", "gvt1.com",
                     "gvt2.com", "googlesyndication.com", "goo.gl", "withgoogle.com"),
          ("8.8.8.8/32", "8.8.4.4/32", "142.250.0.0/15", "142.251.0.0/16", "172.217.0.0/16",
           "172.253.0.0/16", "108.177.0.0/17", "216.58.192.0/19", "74.125.0.0/16",
           "209.85.128.0/17", "64.233.160.0/19", "66.102.0.0/20", "72.14.192.0/18",
           "173.194.0.0/16", "34.64.0.0/10", "35.190.0.0/17")),
    House("Meta", ("facebook.com", "fbcdn.net", "fb.com", "messenger.com", "meta.com",
                   "oculus.com", "threads.net"),
          ("157.240.0.0/16", "31.13.0.0/16", "57.144.0.0/14", "179.60.192.0/22",
           "185.60.216.0/22", "102.132.96.0/20", "69.171.224.0/19")),
    House("Microsoft", ("microsoft.com", "windowsupdate.com", "msftconnecttest.com",
                        "live.com", "office.com", "office365.com", "outlook.com",
                        "sharepoint.com", "azureedge.net", "msn.com", "bing.com",
                        "windows.net", "skype.com", "xboxlive.com"),
          ("13.64.0.0/11", "20.0.0.0/8", "40.64.0.0/10", "52.96.0.0/12", "104.40.0.0/13")),
    House("Amazon", ("amazon.com", "media-amazon.com", "ssl-images-amazon.com",
                     "amazonaws.com", "cloudfront.net", "a2z.com", "amazonvideo.com"),
          ("13.32.0.0/15", "13.35.0.0/16", "18.64.0.0/14", "52.84.0.0/15", "54.230.0.0/16",
           "99.84.0.0/16", "205.251.192.0/19")),
    House("Cloudflare", ("cloudflare.com", "cloudflare-dns.com", "cloudflarestorage.com",
                         "workers.dev", "pages.dev"),
          ("1.1.1.1/32", "1.0.0.1/32", "104.16.0.0/12", "172.64.0.0/13", "162.159.0.0/16",
           "198.41.128.0/17", "188.114.96.0/20")),
    House("Akamai", ("akamai.net", "akamaiedge.net", "akamaized.net", "akadns.net",
                     "akamaitechnologies.com", "edgekey.net", "edgesuite.net"),
          ("23.32.0.0/11", "23.192.0.0/11", "2.16.0.0/13", "104.64.0.0/10", "184.24.0.0/13",
           "96.16.0.0/15")),
    House("Fastly", ("fastly.net", "fastlylb.net"), ("151.101.0.0/16", "199.232.0.0/16")),
    House("Hetzner", (), ("5.9.0.0/16", "78.46.0.0/15", "88.99.0.0/16", "116.202.0.0/15",
                          "135.181.0.0/16", "159.69.0.0/16", "168.119.0.0/16")),
    House("DigitalOcean", ("digitalocean.com", "digitaloceanspaces.com"),
          ("104.131.0.0/16", "138.68.0.0/16", "159.65.0.0/16", "165.227.0.0/16",
           "167.71.0.0/16", "206.189.0.0/16")),
)

@dataclass(frozen=True)
class Overseas:
    """The table of who is out there, and the reading of a name or an address against it.

    Nobody types into it. It used to take a reader's own entries on top of the map's, and the
    one reader it had kept nothing but copies of the map's own there: what a person wants from
    this is the answer, not a form. What the table does not know, the router's own answers —
    now or remembered — are left to say.
    """

    #: Built once: a domain ending → whose it is, and the waters, narrowest first, so a street
    #: inside a district answers before the district does.
    under: dict = field(default_factory=dict, init=False, repr=False, compare=False)
    waters: tuple = field(default=(), init=False, repr=False, compare=False)

    #: Second-level labels a country lets the public register under: bbc.co.uk, not co.uk.
    SHARED: ClassVar[frozenset] = frozenset({"co", "com", "net", "org", "gov", "edu", "ac",
                                            "or", "ne", "go"})

    def __post_init__(self) -> None:
        under: dict = {}
        waters: dict = {}
        for house in HOUSES:
            for ending in house.names:
                under[ending.strip(".").lower()] = house.name
            for block in house.blocks:
                waters[ip_network(block)] = house.name
        object.__setattr__(self, "under", under)
        object.__setattr__(self, "waters",
                           tuple(sorted(waters.items(), key=lambda pair: -pair[0].prefixlen)))

    @classmethod
    def domain(cls, name: str) -> str:
        """The part of a name somebody registered: `http-intake.logs.us5.datadoghq.com` is
        datadoghq.com's.

        Read by rule rather than from the public suffix list, and the rule is plain: the last
        two labels, or three under a country's shared second level. It errs on the odd
        registry, and errs visibly — a name is still shown, only grouped a label too wide."""
        parts = str(name).strip().strip(".").lower().split(".")
        if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in cls.SHARED:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])

    # --- who is at the far end --------------------------------------------------------------
    def by_name(self, name: str) -> str:
        """Whose this name is, read from its end. Empty when nobody claims it.

        The router writes a resolved name with the root dot on it, and a house owns everything
        under its domain, so both are trimmed away one label at a time."""
        parts = str(name).strip().strip(".").lower().split(".")
        for cut in range(len(parts) - 1):
            found = self.under.get(".".join(parts[cut:]))
            if found:
                return found
        return ""

    def by_block(self, address: str) -> str:
        """Whose water this address floats in. A guess by range: blocks change hands."""
        try:
            one = ip_address(str(address).strip())
        except ValueError:
            return ""
        for block, name in self.waters:
            if one in block:
                return name
        return ""

    def whose(self, name: str = "", address: str = "", remembered: bool = False) -> dict:
        """Who is at the far end, and how that came to be known.

        `by` says how: "name" — by the name the router gave just now, which is a fact;
        "memory" — by a name he gave this address before, a guess; "block" — by the range the
        address lies in, a guess as well. A remembered name still outranks a block: it was
        given to this very address, the block only to the street it stands in."""
        found = self.by_name(name)
        if found:
            return {"house": found, "guessed": remembered, "by": "memory" if remembered else "name"}
        found = self.by_block(address)
        return {"house": found, "guessed": True, "by": "block" if found else ""}
