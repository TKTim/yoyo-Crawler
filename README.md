# YoYo English Bot

A LINE bot that scrapes and shares English learning articles from YoYo Club forum.

## LINE Commands

All commands require authorization (user must be in `AUTHORIZED_USER_IDS`).

### `myid`

Shows user ID and group/room ID for debugging.

```
+------------------+
|  User sends      |
|  "myid"          |
+--------+---------+
         |
         v
    +---------+
    | Auth?   | No
    |         |-------> Ignore
    +---------+
         | Yes
         v
+------------------+
|  Get IDs from    |
|  event.source:   |
|  - user_id       |
|  - group_id      |
|  - room_id       |
+--------+---------+
         |
         v
+------------------+
|  Reply with      |
|  ID info         |
+------------------+
```

---

### `db`

Shows all articles stored in database (max 20).

```
+------------------+
|  User sends      |
|  "db"            |
+--------+---------+
         |
         v
    +---------+
    | Auth?   | No
    |         |-------> Ignore
    +---------+
         | Yes
         v
+------------------+
|  Query DB:       |
|  ParsedArticle   |
|  order by date   |
|  limit 20        |
+--------+---------+
         |
         v
+------------------+
|  Reply with      |
|  [date] title    |
|  for each        |
+------------------+
```

---

### `clear`

Deletes all articles from database.

```
+------------------+
|  User sends      |
|  "clear"         |
+--------+---------+
         |
         v
    +---------+
    | Auth?   | No
    |         |-------> Ignore
    +---------+
         | Yes
         v
+------------------+
|  DELETE all      |
|  ParsedArticle   |
+--------+---------+
         |
         v
+------------------+
|  Reply:          |
|  "Deleted X"     |
+------------------+
```

---

### `articles`

Scrapes forum and returns this week's articles with URLs.

```
+------------------+
|  User sends      |
|  "articles"      |
+--------+---------+
         |
         v
    +---------+
    | Auth?   | No
    |         |-------> Ignore
    +---------+
         | Yes
         v
+------------------+      +------------------+
|  parse_forum()   |----->|  Fetch forum     |
|                  |      |  HTML            |
+--------+---------+      +--------+---------+
         |                         |
         |                         v
         |                +------------------+
         |                |  For each topic: |
         |                |  - Parse date    |
         |                |  - Skip future   |
         |                |  - Skip existing |
         |                |  - Save new      |
         |                +--------+---------+
         |                         |
         |<------------------------+
         v
+------------------+
|  Calculate week  |
|  range (Mon-Sun) |
+--------+---------+
         |
         v
+------------------+
|  Query DB:       |
|  articles where  |
|  date in week    |
+--------+---------+
         |
         v
+------------------+
|  Reply:          |
|  [title]: url    |
|  for each        |
+------------------+
```

---

## Cron Job

### `POST /cron/<secret>/`

Scheduled task that scrapes forum and pushes new articles to `PUSH_TARGETS`.

```
+------------------+
|  External cron   |
|  POST request    |
+--------+---------+
         |
         v
    +---------+
    | Valid   | No
    | secret? |-------> 403 Forbidden
    +---------+
         | Yes
         v
+------------------+      +------------------+
|  parse_forum()   |----->|  Fetch forum     |
|  returns NEW     |      |  HTML            |
|  articles only   |      +--------+---------+
+--------+---------+               |
         |                         v
         |                +------------------+
         |                |  For each topic: |
         |                |  - Parse date    |
         |                |    from title    |
         |                |  - Clean URL     |
         |                |    (remove sid)  |
         |                +--------+---------+
         |                         |
         |                         v
         |                    +---------+
         |                    | Future  | Yes
         |                    | article?|---> Skip
         |                    +---------+
         |                         | No
         |                         v
         |                    +---------+
         |                    | Exists  | Yes
         |                    | in DB?  |---> Skip
         |                    +---------+
         |                         | No
         |                         v
         |                +------------------+
         |                |  Save to DB      |
         |                |  (ParsedArticle) |
         |                +--------+---------+
         |                         |
         |                         v
         |                +------------------+
         |                |  Cleanup: keep   |
         |                |  only 20 newest  |
         |                +--------+---------+
         |                         |
         |<------------------------+
         v
+------------------+
|  Filter: only    |
|  articles within |
|  this week       |
+--------+---------+
         |
         v
    +---------+
    | Any new | No
    | this    |-------> Return "No new"
    | week?   |
    +---------+
         | Yes
         v
+------------------+
|  Build message:  |
|  [title]: url    |
+--------+---------+
         |
         v
+------------------+
|  For each target |
|  in PUSH_TARGETS:|
|  - Push message  |
|    via LINE API  |
+--------+---------+
         |
         v
+------------------+
|  Return "OK: X   |
|  articles pushed"|
+------------------+
```

---

## Database

### `ParsedArticle` Model

| Field     | Type      | Description                    |
|-----------|-----------|--------------------------------|
| title     | CharField | Article title with date prefix |
| url       | URLField  | Clean URL (no session ID)      |
| post_date | DateField | Parsed from title (MM/DD)      |

---

## Endpoints

| Endpoint                | Method    | Description                |
|-------------------------|-----------|----------------------------|
| `/callback/`            | POST      | LINE webhook               |
| `/health/`              | GET       | Health check (keep-alive)  |
| `/cron/<secret>/`       | POST      | Cron scraper               |
| `/clear/<secret>/`      | POST      | Clear all articles         |
| `/debug/<secret>/`      | GET       | Debug scraper output       |
| `/users/<secret>/`      | GET, POST | Manage authorized users    |
| `/targets/<secret>/`    | GET, POST | Manage push targets        |

---

## API

All API endpoints require `<secret>` matching the `CRON_SECRET` environment variable. Invalid secret returns `403 Forbidden`.

### `GET /users/<secret>/`

List all authorized users.

**Response** (plain text):
```
Authorized users (2):
  U1234567890abcdef  Tim
  U0987654321fedcba  Alice
```

### `POST /users/<secret>/`

Add or remove an authorized user.

**Parameters** (form data or JSON):

| Parameter | Required | Description            |
|-----------|----------|------------------------|
| `action`  | Yes      | `add` or `remove`      |
| `user_id` | Yes      | LINE user ID           |
| `label`   | No       | Display name for user  |

**Response**:
- Add: `created: <user_id>` or `already exists: <user_id>`
- Remove: `removed: <user_id>` or `not found: <user_id>`
- Missing params: `400 Bad request: need action (add/remove) and user_id`

---

### `GET /targets/<secret>/`

List all push targets.

**Response** (plain text):
```
Push targets (1):
  C1234567890abcdef  English Group
```

### `POST /targets/<secret>/`

Add or remove a push target.

**Parameters** (form data or JSON):

| Parameter   | Required | Description            |
|-------------|----------|------------------------|
| `action`    | Yes      | `add` or `remove`      |
| `target_id` | Yes      | LINE user/group ID     |
| `label`     | No       | Display name for target|

**Response**:
- Add: `created: <target_id>` or `already exists: <target_id>`
- Remove: `removed: <target_id>` or `not found: <target_id>`
- Missing params: `400 Bad request: need action (add/remove) and target_id`
