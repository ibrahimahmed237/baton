"""Additive schema for durable write intents and saved rollback data."""
JOURNAL_SCHEMA = """
create table if not exists journal(
 id integer primary key,
 link_id integer,
 tool text not null,
 chat_id text not null,
 action text not null,
 begun_at text not null,
 state text not null default 'begun',
 pre_receipt text,
 post_receipt text,
 ended_at text not null default '',
 error text not null default ''
);
"""

LINK_SCHEMA = """
create table if not exists links(
  id integer primary key,
  mode text not null,
  paused integer not null default 0,
  created_at text not null,
  removed_at text
);
create table if not exists link_chats(
  link_id integer not null references links(id),
  tool text not null,
  chat text not null,
  active integer not null default 1,
  primary key(link_id, tool)
);
create unique index if not exists one_link_per_chat
  on link_chats(tool, chat) where active = 1;
create table if not exists events(
  id integer primary key,
  link_id integer not null references links(id),
  at text not null,
  kind text not null,
  side text not null default '',
  detail text not null default '{}'
);
create table if not exists turns(
  id integer primary key,
  link_id integer not null references links(id),
  seq integer not null,
  origin text not null,
  origin_id text not null,
  started_at text not null default '',
  ended_at text not null default '',
  first_line text not null default '',
  size integer not null default 0,
  pinned integer not null default 0,
  unique(link_id, origin, origin_id)
);
create table if not exists turn_states(
  turn_id integer not null references turns(id),
  side text not null,
  state text not null,
  local_id text not null default '',
  event_id integer references events(id),
  primary key(turn_id, side)
);
create table if not exists event_turns(
  event_id integer not null references events(id),
  turn_id integer not null references turns(id),
  primary key(event_id, turn_id)
);
"""

COPY_SCHEMA = """
create table if not exists created_copies(
 tool text not null,
 chat_id text not null,
 delivered_at text not null,
 shown integer not null default 0,
 seen_at text,
 primary key(tool,chat_id)
);
"""
