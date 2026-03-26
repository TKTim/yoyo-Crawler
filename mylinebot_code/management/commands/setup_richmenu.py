"""
Management command to create and configure LINE Rich Menu.
Generates a menu image programmatically using Pillow.

Usage:
  python manage.py setup_richmenu --create    # Create & set as default
  python manage.py setup_richmenu --delete    # Delete current default
  python manage.py setup_richmenu --list      # List all rich menus
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
)


# Rich Menu layout: 2500 x 843 (compact), 2 rows x 3 columns
MENU_WIDTH = 2500
MENU_HEIGHT = 843
COLS = 3
ROWS = 2
CELL_W = MENU_WIDTH // COLS
CELL_H = MENU_HEIGHT // ROWS

# Button definitions: (label, action_text, color)
BUTTONS = [
    # Row 1
    ('記錄飲食', 'add ', '#4CAF50'),
    ('今日紀錄', 'today', '#2196F3'),
    ('飲食報告', 'report', '#FF9800'),
    # Row 2
    ('歷史紀錄', 'history', '#9C27B0'),
    ('指令說明', 'help', '#607D8B'),
    ('查看文章', 'articles', '#E91E63'),
]


def _generate_menu_image():
    """Generate rich menu image with Pillow."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGB', (MENU_WIDTH, MENU_HEIGHT), '#FFFFFF')
    draw = ImageDraw.Draw(img)

    # Try to load a font that supports CJK
    font = None
    font_paths = [
        # macOS
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        # Linux
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    ]
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 48)
            break
        except (OSError, IOError):
            continue

    if font is None:
        font = ImageFont.load_default()

    for i, (label, _, color) in enumerate(BUTTONS):
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


def _build_rich_menu_areas():
    """Build area definitions mapping each button region to its action."""
    areas = []
    for i, (label, action_text, _) in enumerate(BUTTONS):
        col = i % COLS
        row = i // COLS

        bounds = RichMenuBounds(
            x=col * CELL_W,
            y=row * CELL_H,
            width=CELL_W,
            height=CELL_H,
        )

        # "add " has a trailing space — opens input for the user to type food
        action = MessageAction(label=label, text=action_text)
        areas.append(RichMenuArea(bounds=bounds, action=action))

    return areas


class Command(BaseCommand):
    help = 'Create and manage LINE Rich Menu'

    def add_arguments(self, parser):
        parser.add_argument('--create', action='store_true', help='Create rich menu and set as default')
        parser.add_argument('--delete', action='store_true', help='Delete current default rich menu')
        parser.add_argument('--list', action='store_true', help='List all rich menus')

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

            # 1. Create rich menu
            rich_menu_request = RichMenuRequest(
                size=RichMenuSize(width=MENU_WIDTH, height=MENU_HEIGHT),
                selected=True,
                name='YoYo Diet Tracker',
                chat_bar_text='開啟選單',
                areas=_build_rich_menu_areas(),
            )

            result = api.create_rich_menu(rich_menu_request)
            menu_id = result.rich_menu_id
            self.stdout.write(f'Rich menu created: {menu_id}')

            # 2. Upload image
            image_buf = _generate_menu_image()
            blob_api.set_rich_menu_image(
                rich_menu_id=menu_id,
                body=image_buf.read(),
                _content_type='image/png',
            )
            self.stdout.write('Image uploaded')

            # 3. Set as default
            api.set_default_rich_menu(menu_id)
            self.stdout.write(self.style.SUCCESS(f'Default rich menu set: {menu_id}'))

    def _delete(self, configuration):
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)

            try:
                default = api.get_default_rich_menu_id()
                menu_id = default.rich_menu_id
                api.cancel_default_rich_menu()
                api.delete_rich_menu(menu_id)
                self.stdout.write(self.style.SUCCESS(f'Deleted default rich menu: {menu_id}'))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'No default rich menu or error: {e}'))

    def _list(self, configuration):
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)

            result = api.get_rich_menu_list()
            if not result.richmenus:
                self.stdout.write('No rich menus found')
                return

            try:
                default = api.get_default_rich_menu_id()
                default_id = default.rich_menu_id
            except Exception:
                default_id = None

            for menu in result.richmenus:
                is_default = ' (DEFAULT)' if menu.rich_menu_id == default_id else ''
                self.stdout.write(f'{menu.rich_menu_id} — {menu.name}{is_default}')
