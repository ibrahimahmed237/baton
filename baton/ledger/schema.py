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
