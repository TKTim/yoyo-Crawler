"""
Management command to create and configure LINE Rich Menu (dual menus with aliases).
Generates menu images programmatically using Pillow.

Usage:
  python manage.py setup_richmenu --create    # Create both menus, aliases & set default
  python manage.py setup_richmenu --delete    # Delete aliases + all menus
  python manage.py setup_richmenu --list      # List all rich menus + aliases
"""
import io

from django.conf import settings
from django.core.management.base import BaseCommand

from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    RichMenuRequest,
    RichMenuArea,
    RichMenuBounds,
    RichMenuSize,
    MessageAction,
    URIAction,
    RichMenuSwitchAction,
    CreateRichMenuAliasRequest,
)


# Rich Menu layout: 2500 x 843 (compact), 2 rows x 3 columns
MENU_WIDTH = 2500
MENU_HEIGHT = 843
COLS = 3
ROWS = 2
CELL_W = MENU_WIDTH // COLS
CELL_H = MENU_HEIGHT // ROWS

# Alias IDs (must match ^[a-z0-9_-]{1,32}$)
ALIAS_MAIN = 'richmenu_main'
ALIAS_MORE = 'richmenu_more'

# Button definitions: (label, action_key, color)
# Special action_key prefixes:
#   __liff__        → URIAction to LIFF editor
#   __liff_add__    → URIAction to LIFF editor in add mode
#   __liff_profile__→ URIAction to LIFF editor in profile mode
#   __menu1__       → RichMenuSwitchAction to main menu
#   __menu2__       → RichMenuSwitchAction to more menu
#   __goal__        → MessageAction with '會員目標'
#   __placeholder__ → MessageAction with '此功能即將推出'
#   anything else   → MessageAction with that text

MENU1_BUTTONS = [
    # Row 1
    ('記錄飲食', '__liff_add__', '#4CAF50'),
    ('今日紀錄', 'today', '#2196F3'),
    ('飲食報告', 'report', '#FF9800'),
    # Row 2
    ('刪除紀錄', 'remove', '#F44336'),
    ('編輯紀錄', '__liff__', '#9C27B0'),
    ('更多功能', '__menu2__', '#607D8B'),
]

MENU2_BUTTONS = [
    # Row 1
    ('會員設定', '__liff_profile__', '#00897B'),
    ('會員目標', '__goal__', '#5C6BC0'),
    ('指令說明', 'help', '#607D8B'),
    # Row 2
    ('即將推出', '__placeholder__', '#BDBDBD'),
    ('即將推出', '__placeholder__', '#BDBDBD'),
    ('返回主選單', '__menu1__', '#455A64'),
]


def _generate_menu_image(buttons):
    """Generate rich menu image with Pillow for the given button list."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGB', (MENU_WIDTH, MENU_HEIGHT), '#FFFFFF')
    draw = ImageDraw.Draw(img)

    # Try to load a font that supports CJK
    font = None
    font_size = 64
    font_paths = [
        # macOS
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        # Ubuntu/Debian — fonts-noto-cjk package
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        # Ubuntu — fonts-noto-cjk-extra or alternate paths
        '/usr/share/fonts/opentype/noto/NotoSansTC-Regular.otf',
        '/usr/share/fonts/truetype/noto/NotoSansTC-Regular.ttf',
        # Ubuntu — WenQuanYi (fonts-wqy-zenhei)
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        # Ubuntu — Droid (fonts-droid-fallback)
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
    ]
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except (OSError, IOError):
            continue

    if font is None:
        # Use glob to find any CJK font on the system
        import glob
        for pattern in ['**/NotoSans*CJK*.ttc', '**/NotoSans*TC*.otf', '**/wqy*.ttc', '**/Droid*Fallback*.ttf']:
            matches = glob.glob(f'/usr/share/fonts/{pattern}', recursive=True)
            if matches:
                try:
                    font = ImageFont.truetype(matches[0], font_size)
                    break
                except (OSError, IOError):
                    continue

    if font is None:
        raise RuntimeError(
            "No CJK font found. Install one with:\n"
            "  sudo apt install fonts-noto-cjk\n"
            "or:\n"
            "  sudo apt install fonts-wqy-zenhei"
        )

    for i, (label, _, color) in enumerate(buttons):
        col = i % COLS
        row = i // COLS
        x0 = col * CELL_W
        y0 = row * CELL_H
        x1 = x0 + CELL_W
        y1 = y0 + CELL_H

        # Draw button background with margin
        margin = 6
        draw.rounded_rectangle(
            [x0 + margin, y0 + margin, x1 - margin, y1 - margin],
            radius=20,
            fill=color,
        )

        # Draw label centered
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = x0 + (CELL_W - tw) // 2
        ty = y0 + (CELL_H - th) // 2
        draw.text((tx, ty), label, fill='#FFFFFF', font=font)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def _build_rich_menu_areas(buttons):
    """Build area definitions mapping each button region to its action."""
    liff_id = settings.LIFF_ID
    areas = []
    for i, (label, action_key, _) in enumerate(buttons):
        col = i % COLS
        row = i // COLS

        bounds = RichMenuBounds(
            x=col * CELL_W,
            y=row * CELL_H,
            width=CELL_W,
            height=CELL_H,
        )

        if action_key == '__liff__':
            action = URIAction(label=label, uri=f'https://liff.line.me/{liff_id}')
        elif action_key == '__liff_add__':
            action = URIAction(label=label, uri=f'https://liff.line.me/{liff_id}?mode=add')
        elif action_key == '__liff_profile__':
            action = URIAction(label=label, uri=f'https://liff.line.me/{liff_id}?mode=profile')
        elif action_key == '__menu1__':
            action = RichMenuSwitchAction(label=label, rich_menu_alias_id=ALIAS_MAIN, data='switch_main')
        elif action_key == '__menu2__':
            action = RichMenuSwitchAction(label=label, rich_menu_alias_id=ALIAS_MORE, data='switch_more')
        elif action_key == '__goal__':
            action = MessageAction(label=label, text='會員目標')
        elif action_key == '__placeholder__':
            action = MessageAction(label=label, text='此功能即將推出')
        else:
            action = MessageAction(label=label, text=action_key)

        areas.append(RichMenuArea(bounds=bounds, action=action))

    return areas


class Command(BaseCommand):
    help = 'Create and manage LINE Rich Menu (dual menus with aliases)'

    def add_arguments(self, parser):
        parser.add_argument('--create', action='store_true', help='Create rich menus and set as default')
        parser.add_argument('--delete', action='store_true', help='Delete all rich menus and aliases')
        parser.add_argument('--list', action='store_true', help='List all rich menus and aliases')

    def handle(self, *args, **options):
        configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)

        if options['create']:
            self._create(configuration)
        elif options['delete']:
            self._delete(configuration)
        elif options['list']:
            self._list(configuration)
        else:
            self.stdout.write('Usage:')
            self.stdout.write('  python manage.py setup_richmenu --create')
            self.stdout.write('  python manage.py setup_richmenu --delete')
            self.stdout.write('  python manage.py setup_richmenu --list')

    def _create(self, configuration):
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)
            blob_api = MessagingApiBlob(api_client)

            # 1. Create main menu (Menu 1)
            menu1_request = RichMenuRequest(
                size=RichMenuSize(width=MENU_WIDTH, height=MENU_HEIGHT),
                selected=True,
                name='YoYo Main Menu',
                chat_bar_text='開啟選單',
                areas=_build_rich_menu_areas(MENU1_BUTTONS),
            )
            result1 = api.create_rich_menu(menu1_request)
            menu1_id = result1.rich_menu_id
            self.stdout.write(f'Main menu created: {menu1_id}')

            # 2. Upload main menu image
            image1_buf = _generate_menu_image(MENU1_BUTTONS)
            blob_api.set_rich_menu_image(
                rich_menu_id=menu1_id,
                body=bytearray(image1_buf.read()),
                _headers={'Content-Type': 'image/png'},
            )
            self.stdout.write('Main menu image uploaded')

            # 3. Create more menu (Menu 2)
            menu2_request = RichMenuRequest(
                size=RichMenuSize(width=MENU_WIDTH, height=MENU_HEIGHT),
                selected=True,
                name='YoYo More Menu',
                chat_bar_text='開啟選單',
                areas=_build_rich_menu_areas(MENU2_BUTTONS),
            )
            result2 = api.create_rich_menu(menu2_request)
            menu2_id = result2.rich_menu_id
            self.stdout.write(f'More menu created: {menu2_id}')

            # 4. Upload more menu image
            image2_buf = _generate_menu_image(MENU2_BUTTONS)
            blob_api.set_rich_menu_image(
                rich_menu_id=menu2_id,
                body=bytearray(image2_buf.read()),
                _headers={'Content-Type': 'image/png'},
            )
            self.stdout.write('More menu image uploaded')

            # 5. Create aliases
            api.create_rich_menu_alias(
                CreateRichMenuAliasRequest(
                    rich_menu_alias_id=ALIAS_MAIN,
                    rich_menu_id=menu1_id,
                )
            )
            self.stdout.write(f'Alias created: {ALIAS_MAIN} → {menu1_id}')

            api.create_rich_menu_alias(
                CreateRichMenuAliasRequest(
                    rich_menu_alias_id=ALIAS_MORE,
                    rich_menu_id=menu2_id,
                )
            )
            self.stdout.write(f'Alias created: {ALIAS_MORE} → {menu2_id}')

            # 6. Set main menu as default
            api.set_default_rich_menu(menu1_id)
            self.stdout.write(self.style.SUCCESS(f'Default rich menu set: {menu1_id}'))

    def _delete(self, configuration):
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)

            # Delete aliases first (they reference menus)
            for alias_id in (ALIAS_MAIN, ALIAS_MORE):
                try:
                    api.delete_rich_menu_alias(alias_id)
                    self.stdout.write(f'Deleted alias: {alias_id}')
                except Exception as e:
                    self.stderr.write(f'Could not delete alias {alias_id}: {e}')

            # Cancel default
            try:
                api.cancel_default_rich_menu()
                self.stdout.write('Cancelled default rich menu')
            except Exception:
                pass

            # Delete all menus
            try:
                result = api.get_rich_menu_list()
                for menu in (result.richmenus or []):
                    api.delete_rich_menu(menu.rich_menu_id)
                    self.stdout.write(f'Deleted menu: {menu.rich_menu_id} ({menu.name})')
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'Error deleting menus: {e}'))

            self.stdout.write(self.style.SUCCESS('All rich menus and aliases deleted'))

    def _list(self, configuration):
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)

            # List menus
            result = api.get_rich_menu_list()
            if not result.richmenus:
                self.stdout.write('No rich menus found')
            else:
                try:
                    default = api.get_default_rich_menu_id()
                    default_id = default.rich_menu_id
                except Exception:
                    default_id = None

                self.stdout.write(f'Rich menus ({len(result.richmenus)}):')
                for menu in result.richmenus:
                    is_default = ' (DEFAULT)' if menu.rich_menu_id == default_id else ''
                    self.stdout.write(f'  {menu.rich_menu_id} — {menu.name}{is_default}')

            # List aliases
            try:
                alias_result = api.get_rich_menu_alias_list()
                aliases = alias_result.aliases or []
                if aliases:
                    self.stdout.write(f'\nAliases ({len(aliases)}):')
                    for alias in aliases:
                        self.stdout.write(f'  {alias.rich_menu_alias_id} → {alias.rich_menu_id}')
                else:
                    self.stdout.write('\nNo aliases found')
            except Exception as e:
                self.stdout.write(f'\nCould not list aliases: {e}')
