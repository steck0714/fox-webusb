# -*- coding: utf-8 -*-
"""
attestation.py
===============
オリジンごとの「ローカルアテステーション」(Ed25519署名)。

実際のChrome WebUSBには存在しない、mock-webusb系列
(pyside6-webusb/tauri-webusb/fox-webusb)独自の追加機能。サイト側が
「このレスポンスが本当に前回と同じローカルブリッジから来たものか」を
検証できるようにする。想定する使い方(TOFU: trust on first use):

  1. 初回訪問時、サイトが getAttestationPublicKey() を呼び、返ってきた
     公開鍵を自分のバックエンド等に保存しておく。
  2. 以降の訪問時、サイトはランダムなchallengeを生成して
     signAttestationChallenge(challenge) を呼び、返ってきた署名を
     保存済みの公開鍵で検証する。署名が正しければ、「秘密鍵を知っている
     (=同じローカルブリッジインスタンスを使い続けている)」ことが、
     鍵を知らない第三者には偽装しようがない形で確認できる。

🛡️ 使っているのは自作の暗号アルゴリズムではなく、確立された、広く検証済みの
Ed25519(RFC 8032)署名方式そのもの(Pythonの`cryptography`パッケージ、
実績のあるOpenSSLベースの実装を利用)。「独自」なのはこの機能を
mock-webusb系列に組み込んで提供するという発想の部分であり、暗号
プリミティブ自体を独自設計してはいない——暗号プリミティブ・プロトコルの
自作は、専門家の間でも「原則としてやってはいけないこと」とされる、
既知の危険なアンチパターンである(数学的に微妙な欠陥が入り込みやすく、
しかもその欠陥は何年も気づかれないことが多い)。

🛡️ 鍵の生成・永続化自体はこのモジュールの関心事ではない
(settings_store.pyのget_or_create_attestation_key_seed()参照、
オリジンごとに完全独立)。このモジュールは「シード(生の秘密鍵バイト列)から
実際の署名/検証を行う」という、状態を持たない純粋な変換処理だけを担う
——bridge.pyのテストがpyusb/実USBデバイスなしで素朴に呼べるように、
という他のモジュール(hardening.py等)と同じ設計方針。

⚠️ このアテステーションが証明するのは「同じ秘密鍵を持つブリッジインスタンス
からの応答である」ことだけである。それ以上の意味(そのマシンの持ち主の
身元、そのマシンが改ざんされていないこと等)を持たせるべきではない——
署名鍵自体はこのホストプロセスが読めるファイルに(平文で)保存されており、
そのマシンへの管理者権限を持つ攻撃者からは当然守れない。あくまで
「ネットワーク越しに応答を偽造する第三者」に対する保証であって、
「ローカルマシン自体を信頼できるという保証」ではない。
"""
import base64

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    HAVE_ATTESTATION = True
except ImportError:
    # 🛡️ HAVE_RUST_ACCEL(bridge.py)と同じ設計方針: `cryptography`パッケージは
    # コンパイル済みのOpenSSLバインディングを必要とするため、環境によっては
    # インストールに失敗し得る。ローカルアテステーションはWebUSBの基本機能
    # (デバイスへの接続・転送等)には一切必要無い、独立した追加機能なので、
    # 無ければ機能を無効化するだけに留め、ホスト全体を落とさない。
    HAVE_ATTESTATION = False

# Ed25519の署名は仕様上常にちょうど64バイト、公開鍵は常にちょうど32バイト。
# challenge自体には特に上限を設けていないが(署名アルゴリズム自体に長さ制限は
# 無い)、素朴なDoS対策として常識的な範囲に収める。
MAX_CHALLENGE_LENGTH = 4096


def public_key_b64_for_seed(seed_b64: str) -> str:
    """base64エンコードされた秘密鍵シード(32バイト)から、対応する公開鍵を
    base64エンコードして返す。"""
    seed = base64.b64decode(seed_b64)
    key = Ed25519PrivateKey.from_private_bytes(seed)
    return base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")


def sign_challenge_b64(seed_b64: str, challenge_b64: str) -> str:
    """base64エンコードされた秘密鍵シードで、base64エンコードされた
    challengeバイト列に署名し、結果をbase64エンコードして返す。
    challengeが長すぎる場合はValueErrorを送出する(呼び出し元がエラー
    レスポンスへ変換する)。"""
    challenge = base64.b64decode(challenge_b64)
    if len(challenge) > MAX_CHALLENGE_LENGTH:
        raise ValueError(f"challenge is too long (max {MAX_CHALLENGE_LENGTH} bytes)")
    seed = base64.b64decode(seed_b64)
    key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = key.sign(challenge)
    return base64.b64encode(signature).decode("ascii")


def verify_signature_b64(public_key_b64: str, challenge_b64: str, signature_b64: str) -> bool:
    """公開鍵・challenge・署名(いずれもbase64)を受け取り、署名が正しければ
    Trueを返す。ホスト側では通常使わない(署名を作る側であって検証する側では
    ない)が、テスト・将来サイト側実装のリファレンスとして提供する。"""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public_key.verify(base64.b64decode(signature_b64), base64.b64decode(challenge_b64))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
