-- Kivo operations workspace. Rows are the shared demo desk, not personal accounts.

create table if not exists brands (
  id text primary key,
  name text not null,
  segment text not null,
  refund_cap integer not null
);

create table if not exists conversations (
  id text primary key,
  brand_id text not null references brands (id),
  channel text not null,
  customer_label text not null,
  subject text not null,
  preview text not null,
  intent text not null,
  status text not null,
  priority text not null,
  ai_handled boolean not null default false,
  confidence integer not null default 0,
  amount_inr integer,
  order_ref text,
  assignee text not null,
  opened_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists conversations_brand_idx on conversations (brand_id, updated_at desc);

create table if not exists messages (
  id serial primary key,
  conversation_id text not null references conversations (id),
  author text not null,
  body text not null,
  citation text,
  created_at timestamptz not null default now()
);

create index if not exists messages_conversation_idx on messages (conversation_id, id);

create table if not exists policies (
  id text primary key,
  brand_id text not null references brands (id),
  title text not null,
  clause text not null,
  body text not null
);

create table if not exists automations (
  id text primary key,
  brand_id text not null references brands (id),
  name text not null,
  trigger_text text not null,
  action_text text not null,
  enabled boolean not null default true,
  runs_7d integer not null default 0
);

create table if not exists quality_scores (
  id text primary key,
  brand_id text not null references brands (id),
  conversation_id text not null references conversations (id),
  agent_kind text not null,
  policy_score integer not null,
  tone_score integer not null,
  resolution_score integer not null,
  note text not null
);

create table if not exists volume_days (
  brand_id text not null references brands (id),
  day date not null,
  inbound integer not null,
  resolved_by_ai integer not null,
  primary key (brand_id, day)
);

insert into brands (id, name, segment, refund_cap) values
  ('northline', 'Northline', 'Apparel', 2000),
  ('mira', 'Mira Pantry', 'Quick commerce', 500)
on conflict (id) do nothing;

insert into conversations (
  id, brand_id, channel, customer_label, subject, preview, intent, status, priority,
  ai_handled, confidence, amount_inr, order_ref, assignee, opened_at, updated_at
) values
  ('c_nl_18420', 'northline', 'whatsapp', 'Meera S.', 'Damaged tee, NL-18420',
   'The black tee arrived with a tear along the seam.', 'return', 'waiting_customer', 'high',
   true, 86, null, 'NL-18420', 'Kivo', now() - interval '3 hours', now() - interval '40 minutes'),
  ('c_nl_18455', 'northline', 'email', 'Arun P.', 'Refund ₹2,500 for a stained jacket',
   'Please refund ₹2,500. The jacket was stained on arrival.', 'refund', 'waiting_approval', 'high',
   true, 91, 2500, 'NL-18455', 'Floor', now() - interval '5 hours', now() - interval '18 minutes'),
  ('c_nl_18302', 'northline', 'chat', 'Leela N.', 'Where is NL-18302',
   'Has NL-18302 shipped?', 'wismo', 'ai_resolved', 'normal',
   true, 94, null, 'NL-18302', 'Kivo', now() - interval '8 hours', now() - interval '7 hours'),
  ('c_nl_18390', 'northline', 'voice', 'Kabir D.', 'Size exchange, tee runs small',
   'Can I exchange the tee for a larger size?', 'exchange', 'open', 'normal',
   false, 62, null, 'NL-18390', 'Floor', now() - interval '70 minutes', now() - interval '12 minutes'),
  ('c_nl_18211', 'northline', 'whatsapp', 'Anika R.', 'Cancel NL-18211 before it ships',
   'Please cancel, it has not shipped.', 'cancel', 'ai_resolved', 'normal',
   true, 97, null, 'NL-18211', 'Kivo', now() - interval '1 day', now() - interval '22 hours'),
  ('c_nl_18501', 'northline', 'email', 'Sana Q.', 'Refund ₹900, wrong colour',
   'The tee is navy. I ordered stone.', 'refund', 'ai_resolved', 'low',
   true, 93, 900, 'NL-18501', 'Kivo', now() - interval '6 hours', now() - interval '5 hours'),
  ('c_nl_18100', 'northline', 'chat', 'Guest', 'Cash on delivery in Hyderabad?',
   'Is COD available in Hyderabad?', 'policy', 'ai_resolved', 'low',
   true, 99, null, null, 'Kivo', now() - interval '2 days', now() - interval '2 days'),
  ('c_mp_9021', 'mira', 'whatsapp', 'Ishan V.', 'Milk and bread missing, MP-9021',
   'Two items were not in the bag.', 'missing_item', 'waiting_approval', 'high',
   true, 88, 640, 'MP-9021', 'Floor', now() - interval '50 minutes', now() - interval '9 minutes'),
  ('c_mp_9044', 'mira', 'chat', 'Riya K.', 'MP-9044 arrived 40 minutes late',
   'The 8 pm slot showed up at 9:38.', 'late', 'ai_resolved', 'normal',
   true, 90, 40, 'MP-9044', 'Kivo', now() - interval '14 hours', now() - interval '13 hours'),
  ('c_mp_8990', 'mira', 'voice', 'Dev P.', 'Received oats instead of muesli',
   'The pack in the bag is the wrong SKU.', 'wrong_item', 'open', 'high',
   false, 58, null, 'MP-8990', 'Floor', now() - interval '35 minutes', now() - interval '6 minutes'),
  ('c_mp_9102', 'mira', 'email', 'Nila T.', 'Spoiled yogurt, MP-9102',
   'The yogurt was warm when the bag arrived.', 'refund', 'ai_resolved', 'normal',
   true, 92, 180, 'MP-9102', 'Kivo', now() - interval '9 hours', now() - interval '8 hours'),
  ('c_mp_9077', 'mira', 'whatsapp', 'Farhan A.', 'Cancel the 9 pm slot',
   'Stop MP-9077, I will not be home.', 'cancel', 'waiting_customer', 'normal',
   true, 84, null, 'MP-9077', 'Kivo', now() - interval '2 hours', now() - interval '25 minutes')
on conflict (id) do nothing;

insert into messages (conversation_id, author, body, citation) values
  ('c_nl_18420', 'customer', $$The black tee from order NL-18420 arrived with a tear along the seam.$$, null),
  ('c_nl_18420', 'kivo', $$Order NL-18420 is on file. Damage at delivery can be returned when you send photos of the tear and the pack. I have not started a refund.$$, $$Clause 8.1.2$$),
  ('c_nl_18420', 'kivo', $$Send two photos: the seam, and the outer pack. A person clears the return only after those arrive.$$, null),
  ('c_nl_18455', 'customer', $$Please refund ₹2,500. The jacket in NL-18455 was stained on arrival.$$, null),
  ('c_nl_18455', 'kivo', $$This refund is ₹2,500, above the ₹2,000 cap. I have held it for a person. Stripe was not called.$$, $$Clause 9.1$$),
  ('c_nl_18302', 'customer', $$Has NL-18302 shipped?$$, null),
  ('c_nl_18302', 'kivo', $$NL-18302 was handed to the delivery partner this morning. The window is today, 2–6 pm. No refund is open.$$, null),
  ('c_nl_18390', 'customer', $$The tee is smaller than the size chart. I want a larger one.$$, null),
  ('c_nl_18390', 'kivo', $$A size exchange is allowed within 7 days if the item is unworn. The voice call asked for a courier pickup, so the floor has this.$$, $$Clause 4.3$$),
  ('c_nl_18390', 'person', $$Pickup is booked for tomorrow between 10 and 1. Keep the tags on.$$, null),
  ('c_nl_18211', 'customer', $$Please cancel NL-18211. It has not shipped.$$, null),
  ('c_nl_18211', 'kivo', $$NL-18211 is still in the warehouse. It can be cancelled before handoff. I have cancelled it. No charge will settle.$$, $$Clause 8.2$$),
  ('c_nl_18501', 'customer', $$The tee is navy. I ordered stone. Please refund ₹900.$$, null),
  ('c_nl_18501', 'kivo', $$Wrong colour is covered. ₹900 is under the cap, so the refund is queued to the original payment method. Stripe is not called in this workspace. The case is resolved by policy.$$, $$Clause 9.1$$),
  ('c_nl_18100', 'customer', $$Is cash on delivery available in Hyderabad?$$, null),
  ('c_nl_18100', 'kivo', $$Northline does not offer cash on delivery. Checkout is UPI, card, and netbanking. I do not have a session to change.$$, $$Clause 3.1$$),
  ('c_mp_9021', 'customer', $$Milk and bread were not in the bag for MP-9021.$$, null),
  ('c_mp_9021', 'kivo', $$Two items are missing on MP-9021. Replacement value is ₹640, above the ₹500 cap. Held for a person. No payment call.$$, $$Clause M.4$$),
  ('c_mp_9044', 'customer', $$The 8 pm slot showed up at 9:38.$$, null),
  ('c_mp_9044', 'kivo', $$The slot was 8–9 pm and the drop was 9:38. A ₹40 late-slot credit applies on the next order. The basket is not refunded.$$, $$Clause M.6$$),
  ('c_mp_8990', 'customer', $$I ordered muesli and received oats.$$, null),
  ('c_mp_8990', 'kivo', $$Wrong SKU on a voice call needs a photo of the pack before a credit. The floor is on this.$$, $$Clause M.3$$),
  ('c_mp_9102', 'customer', $$The yogurt in MP-9102 was warm.$$, null),
  ('c_mp_9102', 'kivo', $$The photo matches a warm perishable. ₹180 is under the cap. Marked for refund to the original method. Stripe stays off in this workspace.$$, $$Clause M.5$$),
  ('c_mp_9077', 'customer', $$Stop MP-9077. I will not be home.$$, null),
  ('c_mp_9077', 'kivo', $$MP-9077 is already with the rider, so it cannot be cancelled. I can convert it to a return when it arrives. Say if you want that.$$, $$Clause M.2$$);

insert into policies (id, brand_id, title, clause, body) values
  ('p_nl_812', 'northline', 'Damage at delivery', 'Clause 8.1.2',
   $$Items substantially damaged at delivery may be returned when the customer sends images of the damage and the pack, and starts the request on the platform.$$),
  ('p_nl_82', 'northline', 'Cancel before handoff', 'Clause 8.2',
   $$An order may be cancelled before it is handed to the delivery partner. After dispatch, cancellation follows the return path.$$),
  ('p_nl_91', 'northline', 'Refunds and the cap', 'Clause 9.1',
   $$Refunds go to the original payment method. Above ₹2,000 a person must approve. The assistant must not say a refund is complete, and must not call Stripe.$$),
  ('p_nl_43', 'northline', 'Size exchange', 'Clause 4.3',
   $$A size exchange is allowed within 7 days if the item is unworn and tags are attached.$$),
  ('p_nl_31', 'northline', 'How you can pay', 'Clause 3.1',
   $$Checkout is UPI, card, and netbanking. Cash on delivery is not offered.$$),
  ('p_mp_m2', 'mira', 'Cancel after the rider has it', 'Clause M.2',
   $$Once an order is with the rider it cannot be cancelled. It can be refused at the door and returned.$$),
  ('p_mp_m3', 'mira', 'Wrong item', 'Clause M.3',
   $$A wrong SKU is credited after a photo of the pack. Voice calls are handed to the floor until the photo arrives.$$),
  ('p_mp_m4', 'mira', 'Missing item and the cap', 'Clause M.4',
   $$Missing items are replaced or refunded at shelf value. Above ₹500 a person approves. No payment call until then.$$),
  ('p_mp_m5', 'mira', 'Perishables', 'Clause M.5',
   $$Warm or spoiled perishables are refunded to the original method when a photo matches, and the amount is under the cap.$$),
  ('p_mp_m6', 'mira', 'Late slot', 'Clause M.6',
   $$A drop more than 30 minutes after the slot earns a ₹40 credit on the next order. The basket is not refunded for lateness alone.$$)
on conflict (id) do nothing;

insert into automations (id, brand_id, name, trigger_text, action_text, enabled, runs_7d) values
  ('a_nl_photos', 'northline', 'Ask before a damaged return', 'Return for damage, no photos on the thread', 'Ask for seam and pack photos. Do not refund.', true, 128),
  ('a_nl_cap', 'northline', 'Hold refunds above the cap', 'Refund amount over ₹2,000', 'Set waiting approval. Skip Stripe.', true, 17),
  ('a_nl_cancel', 'northline', 'Cancel in the warehouse', 'Cancel request and order not yet handed off', 'Cancel the order and resolve.', true, 46),
  ('a_nl_block', 'northline', 'Block off-policy asks', 'Prompt injection or a request outside support', 'Refuse and do not call a tool.', true, 9),
  ('a_mp_cap', 'mira', 'Hold credits above ₹500', 'Missing item or refund over ₹500', 'Set waiting approval. Skip payment.', true, 22),
  ('a_mp_late', 'mira', 'Late slot credit', 'Drop more than 30 minutes after the slot', 'Apply ₹40 next-order credit. Resolve.', true, 61),
  ('a_mp_rider', 'mira', 'No cancel once riding', 'Cancel after rider assignment', 'Explain Clause M.2 and offer a door refusal.', true, 33),
  ('a_mp_photo', 'mira', 'Photo before wrong-SKU credit', 'Wrong item on voice or chat, no photo', 'Ask for the pack photo and hand to the floor.', true, 19)
on conflict (id) do nothing;

insert into quality_scores (id, brand_id, conversation_id, agent_kind, policy_score, tone_score, resolution_score, note) values
  ('q1', 'northline', 'c_nl_18455', 'ai', 98, 84, 90, 'Cited 9.1, named the cap, and did not imply the refund was sent.'),
  ('q2', 'northline', 'c_nl_18302', 'ai', 92, 88, 96, 'Gave the window without inventing a tracking link.'),
  ('q3', 'northline', 'c_nl_18390', 'human', 80, 90, 74, 'Pickup was booked. The tags reminder should have been in the first reply.'),
  ('q4', 'northline', 'c_nl_18501', 'ai', 96, 86, 94, 'Under-cap refund queued without telling the customer the money had moved.'),
  ('q5', 'mira', 'c_mp_9021', 'ai', 97, 82, 88, 'Held ₹640 correctly. Tone is a little clipped for a missing staple.'),
  ('q6', 'mira', 'c_mp_9044', 'ai', 94, 91, 93, 'Credit, not a basket refund. Matches M.6.'),
  ('q7', 'mira', 'c_mp_8990', 'human', 70, 86, 60, 'Still waiting on the pack photo. The floor has not sent the ask in the customer''s words.'),
  ('q8', 'northline', 'c_nl_18100', 'ai', 99, 80, 95, 'Correct refusal of COD. Could name the three methods more plainly.')
on conflict (id) do nothing;

insert into volume_days (brand_id, day, inbound, resolved_by_ai) values
  ('northline', current_date - 13, 38, 24),
  ('northline', current_date - 12, 44, 29),
  ('northline', current_date - 11, 41, 27),
  ('northline', current_date - 10, 52, 36),
  ('northline', current_date - 9, 47, 31),
  ('northline', current_date - 8, 36, 22),
  ('northline', current_date - 7, 33, 21),
  ('northline', current_date - 6, 49, 34),
  ('northline', current_date - 5, 55, 39),
  ('northline', current_date - 4, 46, 32),
  ('northline', current_date - 3, 51, 37),
  ('northline', current_date - 2, 43, 30),
  ('northline', current_date - 1, 48, 35),
  ('northline', current_date, 22, 14),
  ('mira', current_date - 13, 80, 61),
  ('mira', current_date - 12, 92, 70),
  ('mira', current_date - 11, 88, 66),
  ('mira', current_date - 10, 101, 79),
  ('mira', current_date - 9, 96, 74),
  ('mira', current_date - 8, 74, 55),
  ('mira', current_date - 7, 69, 50),
  ('mira', current_date - 6, 94, 73),
  ('mira', current_date - 5, 110, 86),
  ('mira', current_date - 4, 99, 77),
  ('mira', current_date - 3, 105, 82),
  ('mira', current_date - 2, 91, 68),
  ('mira', current_date - 1, 97, 75),
  ('mira', current_date, 41, 30)
on conflict (brand_id, day) do nothing;
