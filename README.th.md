# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge เป็นโปรเจกต์ local bridge แบบไม่เป็นทางการ สำหรับส่งคำขอ reasoning ของ Codex Desktop / Codex CLI ไปยัง ChatGPT Web ที่ล็อกอินไว้แล้ว โดยยังคงให้การเข้าถึงไฟล์, Shell, การแก้ไขโค้ด, การทดสอบ, Git, sandbox และ approval ทำงานผ่าน Codex client ในเครื่องของผู้ใช้

> สถานะ release candidate: S1/S2 ปิดแล้ว และ real Codex Desktop E2E ของ standalone ได้พิสูจน์ same-thread context, local-tool execution จริง, route `uwa / chatgpt / high` และ request cleanup แล้ว จะสร้าง tag ของ RC แรกก็ต่อเมื่อ final S3 live, Desktop E2E, clean-install smoke, CI และ S4 release gate ผ่านบน candidate SHA เดียวกันทั้งหมด
>
> เอกสารนี้ไม่ยึด blocker ชั่วคราวจาก live run ใด run หนึ่ง การตัดสิน release ใช้ candidate-bound gate evidence เท่านั้น เมื่อ HEAD เปลี่ยนต้องสร้าง live evidence ที่เกี่ยวข้องใหม่


## เริ่มต้นใช้งานอย่างรวดเร็ว

ระหว่างการพัฒนาให้ใช้สาขา `standalone-dev`

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

สลับ Codex ไปยัง Web Bridge:

```bash
codex-uwa
```

กลับไปใช้ route ทางการของ Codex:

```bash
codex-official
```

ตรวจสถานะ:

```bash
codex-uwa-status
```

หยุด local bridge:

```bash
codex-uwa-stop
```

endpoint เริ่มต้น:

```text
http://127.0.0.1:8199
```

ตรวจสุขภาพบริการ:

```bash
curl -sS http://127.0.0.1:8199/health
```

## สถาปัตยกรรม

```text
Codex Desktop / CLI
  workspace, shell, edit, test, Git, sandbox, approval
        |
        v
Codex Web Bridge
  Responses compatibility, routing, continuity, compaction, browser transport
        |
        v
ChatGPT Web session ที่ล็อกอินแล้ว
```

หน้าเว็บจะไม่ได้รับสิทธิ์เข้าถึง filesystem ในเครื่องโดยตรง เมื่อจำเป็นต้องใช้ local tool จริง Bridge จะส่ง standard Responses `function_call` กลับไปให้ Codex client รันในเครื่อง แล้ว client จะส่ง `function_call_output` กลับเข้าสู่ turn เดิม

route ที่ควบคุมอยู่ในปัจจุบัน:

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

## ขอบเขตหลักของระบบ

1. Codex client เป็นผู้มีอำนาจในการรัน local tool เสมอ Bridge จะไม่ข้าม client ไปแก้ไข workspace โดยตรง
2. provider, model และ reasoning effort ต้องตรวจสอบได้จาก config, session metadata และ wire evidence
3. ถ้ากำหนดให้ต้องใช้ local tool จริง การพิมพ์ข้อความเลียนแบบ tool call ไม่นับว่าผ่าน ต้องเกิด `function_call -> local execution -> function_call_output` จริง
4. same-thread continuation, UWA restart, Web conversation affinity และ native/remote compaction ต้องรักษาความต่อเนื่องเชิงตรรกะ และ fail closed เมื่อพิสูจน์ความถูกต้องไม่ได้
5. จะไม่ replay local tool แบบอัตโนมัติเมื่อสถานะ side effect ไม่แน่นอน
6. public repository จะไม่เก็บ private prompt, command body, tool output, cookies, browser profile หรือ full wire trace

## ข้อกำหนดการยอมรับ RC

หลักฐาน release ทั้งหมดต้องผูกกับ candidate commit เดียวกัน:

```text
S1 / S2                                         PASS / CLOSED
standalone non-live regression                  PASS
Codex Desktop E2E                               REQUIRED ON CANDIDATE
S3 CLI/live parity                              REQUIRED: PASS_LIVE_CLOSED
clean-checkout install smoke                    REQUIRED
S4 docs/version/security/provenance gate        REQUIRED
CI                                              REQUIRED
```

Desktop gate พิสูจน์ Desktop จริง, same-thread context, local tools และ route ส่วน S3 พิสูจน์ restart, native/remote compaction, post-compaction recovery, route และ request cleanup หลักฐานที่ SHA ไม่ตรงกับ HEAD ปัจจุบันใช้ release ไม่ได้

## Continuity และ long context

ระบบรองรับ `previous_response_id`, call-id continuity, Web conversation affinity, private persisted continuity state, native auto-compaction และ Remote V2 compaction

Remote V2 compaction ใช้ controlled envelope พร้อม internal compaction lineage การนำ required-tool completion กลับมาใช้ซ้ำจะทำเฉพาะเมื่อพิสูจน์ได้ว่าเป็น compaction lineage และ user turn เดียวกัน เพื่อป้องกันการบังคับรัน local tool ซ้ำหลัง function-call history ถูก compact และเพื่อป้องกัน state leakage ระหว่าง thread

## Baseline ที่ผ่านการตรวจสอบ

standalone extraction รุ่นแรกอ้างอิงจาก:

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

integrated baseline นี้ผ่าน Stage A-F, real client-tool round trip, same-thread/restart continuity, native/remote compaction, Desktop acceptance, stream cancellation cleanup, final regression และ M1-M7 integrated release gates แล้ว

อย่างไรก็ตาม standalone repository ต้องผ่าน S3 ของตัวเองก่อนจึงจะถือเป็น release evidence

## การพัฒนาและการปล่อยเวอร์ชัน

การพัฒนาทำบน `standalone-dev` และ `main` ยังคงเป็น release boundary รุ่น candidate แรกที่วางแผนไว้คือ:

```text
v0.1.0-rc.1
```

หลังจากผ่าน independent S3 live parity, safety checks, dependency/provenance audit และ release artifact validation แล้วจึงจะไปยัง:

```text
v0.1.0
```

## ความปลอดภัยและความเป็นส่วนตัว

```text
API bind       127.0.0.1
remote access  ปิดโดยค่าเริ่มต้น
CORS           ปิดโดยค่าเริ่มต้น
unsafe Python  ปิด
private state  ~/.uwa
```

ห้าม commit credentials, cookies, browser profiles, private prompts, command/tool bodies, private Responses persistence, raw browser/session identifiers หรือ full wire traces

ดูนโยบายเพิ่มเติมที่ [SECURITY.md](SECURITY.md)

## License และที่มา

โปรเจกต์นี้สืบทอดจาก [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api) ผ่าน integration tree ที่ผ่านการตรวจสอบใน `lxxlx2/universal-web-api` โค้ดที่สืบทอดจาก upstream ยังคงอยู่ภายใต้ GNU Affero General Public License v3.0 และ copyright notice ที่เกี่ยวข้อง

ดูรายละเอียดที่ [NOTICE.md](NOTICE.md) และ [LICENSE](LICENSE)

## ประกาศโปรเจกต์ไม่เป็นทางการ

Codex Web Bridge เป็นโปรเจกต์ด้าน interoperability, learning และ engineering ที่เป็นอิสระ ไม่ใช่ผลิตภัณฑ์ทางการของ OpenAI, ChatGPT หรือ Codex และไม่ได้หมายถึงการเป็นพันธมิตร การอนุญาต การรับรอง หรือการสนับสนุนจาก OpenAI หรือบุคคลที่สาม

โปรเจกต์นี้ไม่แก้ไขหรือข้ามสิทธิ์บัญชี, subscription limits, quotas, model permissions หรือ platform safety controls ผู้ใช้ต้องรับผิดชอบต่อการปฏิบัติตามข้อกำหนดของซอฟต์แวร์ เว็บไซต์ บริการ นโยบายขององค์กร และกฎหมายที่เกี่ยวข้อง รวมถึงคำสั่งและการเปลี่ยนแปลงโค้ดที่รันในเครื่องของตนเอง
