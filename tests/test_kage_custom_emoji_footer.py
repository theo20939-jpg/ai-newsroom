"""KAGE footer: Unicode 🥷 + linked KAGE by default; a branded custom emoji only when validly configured."""
from __future__ import annotations

import html
from html.parser import HTMLParser
from uuid import UUID

import pytest
from aiogram.methods import SendPhoto
from aiogram.types import MessageEntity
from aiogram.utils.text_decorations import html_decoration

from bot.keyboards.image_preview import build_editorial_send_keyboard
from core.config import settings
from services.news_telegram_presentation import build_ninja_pulse_footer_html, render_v81_news_card_html

NINJA = "\U0001F977"  # 🥷
LINK = '<a href="https://t.me/kage_journal">KAGE</a>'
NINJA_FOOTER = f"{NINJA} {LINK}"
EMOJI_ID = "5368324170671202286"  # Bot API docs example id - NOT the real KAGE emoji
FALLBACK = NINJA
CANARY_TITLE = "На даркнет-маркетплейсах продают доступ к ИИ-моделям со скидками до 97%"
CANARY_BODY = ("Google Threat Intelligence Group обнаружила предложения доступа к моделям "
               "Anthropic, Google и OpenAI.")
CANARY_EVENT = UUID("0c61fab4-90ca-4cf8-a9d8-1e6909a5c027")


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class _TelegramHtml(HTMLParser):
    """Minimal Telegram-HTML -> (text, entities) parser; offsets in UTF-16 code units, as the
    Bot API measures them. Only the tags this footer/card emit are understood."""

    _TYPES = {"b": "bold", "a": "text_link", "tg-emoji": "custom_emoji", "blockquote": "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text = ""
        self.open: list[tuple[str, int, dict]] = []
        self.entities: list[dict] = []

    def handle_starttag(self, tag, attrs):
        assert tag in self._TYPES, f"unexpected tag {tag}"
        self.open.append((tag, _utf16(self.text), dict(attrs)))

    def handle_endtag(self, tag):
        name, start, attrs = self.open.pop()
        assert name == tag
        entity = {"type": self._TYPES[tag], "offset": start, "length": _utf16(self.text) - start}
        if tag == "a":
            entity["url"] = attrs["href"]
        if tag == "tg-emoji":
            entity["custom_emoji_id"] = attrs["emoji-id"]
        self.entities.append(entity)

    def handle_data(self, data):
        self.text += data


def _parse(markup: str) -> tuple[str, list[dict]]:
    parser = _TelegramHtml()
    parser.feed(markup)
    parser.close()
    assert not parser.open
    return parser.text, sorted(parser.entities, key=lambda e: (e["offset"], -e["length"]))


def _utf16_slice(text: str, offset: int, length: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le")


def _card(title: str = CANARY_TITLE, body: str = CANARY_BODY) -> str:
    return render_v81_news_card_html({"title": title, "main_body": body}, include_ninja_pulse_footer=True)


@pytest.fixture(autouse=True)
def release_default(monkeypatch):
    """This release: no custom emoji configured (the production default)."""
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", None)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", None)


@pytest.fixture
def emoji_configured(monkeypatch):
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", EMOJI_ID)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", FALLBACK)


# --- this release: Unicode ninja footer ------------------------------------------------------

def test_release_footer_is_unicode_ninja_then_linked_kage():
    footer = build_ninja_pulse_footer_html()
    assert footer == NINJA_FOOTER
    assert footer.encode("utf-8").startswith(b"\xf0\x9f\xa5\xb7 ")  # U+1F977, a normal Unicode emoji
    text, entities = _parse(footer)
    assert text == f"{NINJA} KAGE"
    # Only KAGE is linked; 🥷 is plain text (2 UTF-16 units) - no custom_emoji entity at all.
    assert entities == [{"type": "text_link", "offset": 3, "length": 4, "url": "https://t.me/kage_journal"}]


def test_release_card_emits_no_custom_emoji_entity_and_links_kage():
    markup = _card()
    assert "<tg-emoji" not in markup
    text, entities = _parse(markup)
    assert not [e for e in entities if e["type"] == "custom_emoji"]
    links = [e for e in entities if e["type"] == "text_link"]
    assert len(links) == 1 and links[0]["url"] == "https://t.me/kage_journal"
    assert _utf16_slice(text, links[0]["offset"], links[0]["length"]) == "KAGE"
    assert text.endswith(f"{NINJA} KAGE")


@pytest.mark.parametrize("title,body", [
    (CANARY_TITLE, CANARY_BODY),
    ("Запуск 🚀 и 𝕏: 👨‍👩‍👧 семья", "Текст с астральными символами 😀🧪 и кириллицей & <знаками>."),
])
def test_cyrillic_and_astral_text_before_the_ninja_footer_keep_utf16_offsets(title, body):
    markup = _card(title, body)
    text, entities = _parse(markup)
    link = [e for e in entities if e["type"] == "text_link"][0]
    prefix = text[: text.rindex("KAGE")]
    assert prefix.endswith(f"{NINJA} ")
    assert link["offset"] == _utf16(prefix)  # UTF-16 units: 🥷 and any astral chars count 2
    assert _utf16_slice(text, link["offset"], link["length"]) == "KAGE"
    rebuilt = html_decoration.unparse(text, [MessageEntity(**e) for e in entities])
    assert _parse(rebuilt) == (text, entities)  # aiogram's own UTF-16 entity model agrees


def test_utf16_length_accounting_counts_the_ninja_as_two_units():
    assert _utf16(NINJA) == 2 and len(NINJA) == 1
    assert _utf16(NINJA_FOOTER) == _utf16(LINK) + 3
    visible = _parse(_card())[0]
    assert _utf16(visible) == len(visible) + 1  # the only astral character in the canary card is 🥷


def test_photo_caption_payload_keeps_the_ninja_footer_within_caption_limits():
    caption = _card()
    payload = SendPhoto(chat_id=-1004297182444, message_thread_id=2, photo="file-id",
                        caption=caption, parse_mode="HTML").model_dump(exclude_none=True)
    assert payload["caption"] == caption and payload["parse_mode"] == "HTML"
    assert payload["caption"].endswith(NINJA_FOOTER)
    assert _utf16(caption) <= 1024


def test_source_and_meme_buttons_unchanged():
    labels = [b["text"] for row in build_editorial_send_keyboard("https://example.com/a", CANARY_EVENT)
              .model_dump()["inline_keyboard"] for b in row]
    assert labels == ["🔗 Источник", "😂 Сгенерировать мем"]


def test_no_duplicate_footer():
    markup = _card()
    assert markup.count("https://t.me/kage_journal") == 1
    assert markup.count(NINJA) == 1
    assert _parse(markup)[0].count("KAGE") == 1


def test_accepted_canary_replay_only_the_footer_is_the_ninja_footer():
    markup = _card()
    assert markup == f"<b>{html.escape(CANARY_TITLE, quote=False)}</b>\n\n{CANARY_BODY}\n\n{NINJA_FOOTER}"


# --- future path: branded custom emoji, only when validly configured (disabled in this release) ---

def test_release_default_has_no_custom_emoji_configuration():
    assert settings.kage_telegram_custom_emoji_id is None
    assert settings.kage_telegram_custom_emoji_fallback is None


def test_future_configured_custom_emoji_replaces_the_ninja(emoji_configured):
    footer = build_ninja_pulse_footer_html()
    assert footer == f'<tg-emoji emoji-id="{EMOJI_ID}">{FALLBACK}</tg-emoji> {LINK}'
    text, entities = _parse(footer)
    assert text == f"{FALLBACK} KAGE"
    assert entities[0] == {"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": EMOJI_ID}
    assert _card().count("<tg-emoji") == 1 and _card().count(NINJA) == 1


@pytest.mark.parametrize("emoji_id,fallback", [
    ("", FALLBACK), ("   ", FALLBACK), ("abc", FALLBACK), ("12 34", FALLBACK), ("12a", FALLBACK),
    ('1"><b>x', FALLBACK), ("1" * 33, FALLBACK), (EMOJI_ID, None), (EMOJI_ID, ""), (EMOJI_ID, "K"),
    (EMOJI_ID, "KAGE"), (EMOJI_ID, "🥷 x"), (EMOJI_ID, "<b>"), (EMOJI_ID, "🥷" * 9),
])
def test_invalid_or_partial_custom_configuration_keeps_the_unicode_ninja(monkeypatch, emoji_id, fallback):
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", emoji_id)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", fallback)
    assert build_ninja_pulse_footer_html() == NINJA_FOOTER
