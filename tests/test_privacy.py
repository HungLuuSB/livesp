import unittest

from livesp.capture import privacy

SALT = b"unit-test-salt-0123456789"


class TestPrivacy(unittest.TestCase):
    def test_hash_stable_and_case_insensitive(self):
        self.assertEqual(privacy.hash_id("@Lan.Nguyen", SALT), privacy.hash_id("lan.nguyen", SALT))
        self.assertNotEqual(privacy.hash_id("a", SALT), privacy.hash_id("a", b"other-salt-0123456789"))

    def test_mentions_hashed(self):
        out = privacy.hash_mentions("@lan.nguyen mua đi", SALT)
        self.assertTrue(out.startswith("@u_"))
        self.assertNotIn("lan.nguyen", out)

    def test_pii_masked(self):
        self.assertEqual(privacy.mask_pii("sdt 0912 345 678 nha"), "sdt <SĐT> nha")
        self.assertIn("<EMAIL>", privacy.mask_pii("mail a.b@gmail.com"))
        self.assertEqual(privacy.mask_pii("giá 99k"), "giá 99k")

    def test_scrub_payload(self):
        p = {"user": {"nickname": "Lan", "unique_id": "lan.nguyen", "avatar_thumb": {"url_list": ["x"]}}, "content": "hi"}
        out = privacy.scrub_payload(p, SALT)
        self.assertNotIn("nickname", out["user"])
        self.assertNotIn("avatar_thumb", out["user"])
        self.assertNotEqual(out["user"]["unique_id"], "lan.nguyen")

    def test_scrub_payload_camelcase_user_collapsed(self):
        # betterproto to_dict trả camelCase; id số của user cũng là định danh
        p = {"pinMessage": {"user": {"displayId": "Lan.Nguyen", "nickname": "Lan", "id": "7001", "secUid": "s"}}}
        out = privacy.scrub_payload(p, SALT)
        self.assertEqual(out["pinMessage"]["user"], {"unique_id": privacy.hash_id("lan.nguyen", SALT)})
        self.assertNotIn("7001", str(out))

    def test_scrub_payload_id_keys_and_strings(self):
        p = {"fromUserId": 123456, "anchor_uid": "999", "mention_user_list": [1, 2], "to_member_nickname": "Lan",
             "contributor_avatar": {"x": 1}, "gift_id": 5, "member_count": 10, "room_id": 77,
             "content": "@lan.nguyen gọi 0912345678"}
        out = privacy.scrub_payload(p, SALT)
        self.assertEqual(out["fromUserId"], privacy.hash_id(123456, SALT))
        self.assertEqual(out["anchor_uid"], privacy.hash_id("999", SALT))
        self.assertEqual(out["mention_user_list"], [privacy.hash_id(1, SALT), privacy.hash_id(2, SALT)])
        self.assertNotIn("to_member_nickname", out)
        self.assertNotIn("contributor_avatar", out)
        self.assertEqual((out["gift_id"], out["member_count"], out["room_id"]), (5, 10, 77))
        self.assertNotIn("lan.nguyen", out["content"])
        self.assertIn("<SĐT>", out["content"])
