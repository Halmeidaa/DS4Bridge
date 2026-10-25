# -*- coding: utf-8 -*-
"""DS4 Bridge 2.2.5 - adaptador USB DS4 -> XInput Xbox 360 no Windows.

Mantenha ViGEmBus; para eliminar o input duplicado instale HidHide e use
'Ocultar controle fisico' em Configurar HidHide.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Definido antes da inicializacao da janela para texto nitido em monitores HiDPI.
if sys.platform == "win32":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError, ValueError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

def exibir_erro_inicio(erro: BaseException) -> None:
    """Mostra erros que pythonw.exe esconderia e grava diagnóstico local."""
    import traceback
    detalhe = "".join(traceback.format_exception(type(erro), erro, erro.__traceback__))
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DS4Bridge"
    arquivo = local / "erro_inicio.log"
    try:
        local.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(detalhe, encoding="utf-8")
    except OSError:
        arquivo = None
    resumo = (
        "Não foi possível iniciar o DS4 Bridge.\n\n"
        + f"Erro: {erro}\n\n"
        + (f"Detalhes salvos em: {arquivo}\n\n" if arquivo else "")
        + "Abra pelo arquivo Iniciar.bat ou execute instalar.bat uma vez."
    )
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, resumo[:1800], "DS4 Bridge — erro de inicialização", 0x10)
    else:
        print(resumo, file=sys.stderr)

try:
    import customtkinter as ctk
    from tkinter import Canvas, messagebox
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except Exception as exc:
    exibir_erro_inicio(exc)
    raise SystemExit(1) from exc

VERSION = "2.2.5"
VIGEM_URL = "https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0"
HIDHIDE_URL = "https://github.com/nefarius/HidHide/releases"
BG = "#0a0f19"
PANEL = "#121c2b"
PANEL_LIGHT = "#192638"
BORDER = "#27384e"
TEXT = "#edf5ff"
MUTED = "#94a9c3"
CYAN = "#53d9d0"
GREEN = "#6debaf"
AMBER = "#ffcf78"
RED = "#ff7d94"
FONT = "Segoe UI"

# Bits dos botoes XUSB_GAMEPAD no ViGEm (mapeamento DS4 USB 0x01).
KEYS = (
    ("✕   A", 0x1000), ("○   B", 0x2000), ("□   X", 0x4000), ("△   Y", 0x8000),
    ("L1  LB", 0x0100), ("R1  RB", 0x0200), ("L3", 0x0040), ("R3", 0x0080),
    ("SHARE", 0x0020), ("OPTIONS", 0x0010), ("PS", 0x0400),
    ("CIMA", 0x0001), ("DIR.", 0x0008), ("BAIXO", 0x0002), ("ESQ.", 0x0004),
)
DPAD = (0x0001, 0x0001 | 0x0008, 0x0008, 0x0008 | 0x0002,
        0x0002, 0x0002 | 0x0004, 0x0004, 0x0004 | 0x0001, 0)
SONY_VID = 0x054C
SONY_PRODUCTS = {0x05C4, 0x09CC}


def clipped(value: float, a: float = -1.0, b: float = 1.0) -> float:
    return max(a, min(b, value))


def normalized_axis(raw: int) -> float:
    # Permite atingir -1 e +1; centro de 128 e 0.
    return (raw - 128) / (128 if raw < 128 else 127)


def stick(x: int, y: int, deadzone: float) -> tuple[float, float]:
    """Deadzone radial em vez de axial; evita 'eixos duros' na direcao."""
    a, b = normalized_axis(x), -normalized_axis(y)
    magnitude = math.hypot(a, b)
    if magnitude <= deadzone:
        return (0.0, 0.0)
    # Mantem os valores de direcao na borda circular e a resposta linear.
    # Nao arredondar aqui: curvas de direcao suaves precisam de precisao.
    factor = (min(magnitude, 1.0) - deadzone) / (1.0 - deadzone) / magnitude
    return (clipped(a * factor), clipped(b * factor))


def parse_report(raw: list[int] | bytes, deadzone: float = 0.02) -> dict:
    """Aceita HID USB DS4 0x01 e report curto equivalente de alguns clones.

    Nao adivinha outros layouts: transmitir offsets errados faz botoes aleatorios.
    """
    if not 0.0 <= deadzone <= 0.35:
        raise ValueError("Zona morta deve ficar entre 0% e 35%.")
    if len(raw) < 10 or raw[0] != 0x01:
        ident = f"0x{raw[0]:02X}" if raw else "vazio"
        raise ValueError(
            f"Relatorio HID nao suportado (ID {ident}, {len(raw)} bytes). "
            "Este controle precisa usar o layout DS4 USB (ID 0x01, >= 10 bytes)."
        )
    hat = raw[5] & 0x0F
    if hat > 8:
        raise ValueError(f"Direcao D-pad invalida no relatorio HID: {hat}")
    bits = DPAD[hat]
    for byte, mask, xusb in (
        (5, 0x10, 0x4000), (5, 0x20, 0x1000),
        (5, 0x40, 0x2000), (5, 0x80, 0x8000),
        (6, 0x01, 0x0100), (6, 0x02, 0x0200),
        (6, 0x10, 0x0020), (6, 0x20, 0x0010),
        (6, 0x40, 0x0040), (6, 0x80, 0x0080),
        (7, 0x01, 0x0400),
    ):
        if raw[byte] & mask:
            bits |= xusb
    touchpad = bool(raw[7] & 0x02)
    # Caso o clone so envie o bit digital de L2/R2, mantenha os gatilhos usaveis.
    lt = raw[8] if raw[8] > 0 else (255 if raw[6] & 0x04 else 0)
    rt = raw[9] if raw[9] > 0 else (255 if raw[6] & 0x08 else 0)
    return {
        "buttons": bits,
        "left": stick(raw[1], raw[2], deadzone),
        "right": stick(raw[3], raw[4], deadzone),
        "lt": lt, "rt": rt,
        "touchpad": touchpad,
    }


def state_for_virtual(state: dict) -> dict:
    # PS / Guide nunca e enviado: evita Xbox Game Bar.
    # Click touchpad compartilha Back para ter funcao pratica em jogos.
    bits = state["buttons"] & ~0x0400
    if state["touchpad"]:
        bits |= 0x0020
    return {**state, "buttons": bits}


def send_pad(pad, state: dict) -> None:
    # Os estados sao sempre montados por inteiro. Apenas enviar QUANDO mudar.
    pad.reset()
    if state["buttons"]:
        pad.press_button(button=state["buttons"])
    pad.left_joystick_float(x_value_float=state["left"][0], y_value_float=state["left"][1])
    pad.right_joystick_float(x_value_float=state["right"][0], y_value_float=state["right"][1])
    pad.left_trigger(value=state["lt"])
    pad.right_trigger(value=state["rt"])
    pad.update()


def maybe_controller(d: dict) -> bool:
    """DS4 oficial ou clone USB com descricao tipica de controle PS4."""
    if d.get("bus_type", 1) not in (0, 1):
        return False
    if d.get("usage_page") not in (0, 1, None) or d.get("usage") not in (0, 4, 5, None):
        return False
    vid = d.get("vendor_id", 0)
    pid = d.get("product_id", 0)
    name = ((d.get("product_string") or "") + " " + (d.get("manufacturer_string") or "")).lower()
    if vid == SONY_VID and (pid in SONY_PRODUCTS or "controller" in name):
        return True
    return ("wireless controller" in name or "dualshock" in name or "ps4 controller" in name)


class Bridge:
    """Worker de alta prioridade para leitura HID sem interagir com widgets Tk."""
    def __init__(self):
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.events = queue.SimpleQueue()
        self.deadzone = 0.02
        self.state: dict | None = None
        self.virtual_state: dict | None = None
        self.virtual_on = False
        self.connected = False
        self.report_time = 0.0
        self.fps = 0.0
        self.interval_ms = None
        self.mode = "idle"

    def launch(self, path: bytes, virtual: bool) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.connected = False
        self.virtual_on = False
        self.mode = "starting"
        self.fps = 0.0
        self.interval_ms = None
        self.thread = threading.Thread(target=self.run, args=(path, virtual), daemon=True)
        self.thread.start()

    def run(self, path: bytes, output: bool) -> None:
        device = pad = None
        last_rx = time.monotonic()
        pending_virtual: dict | None = None
        last_sent: dict | None = None
        last_sample = last_rx
        count = 0
        rejected = 0
        try:
            import hid
            device = hid.device()
            device.open_path(path)
            try:
                device.set_nonblocking(False)
            except AttributeError:
                pass
            if output:
                try:
                    import vgamepad as vg
                    pad = vg.VX360Gamepad()
                except Exception as exc:
                    detalhe = str(exc)
                    texto = detalhe.lower()
                    if "vigemclient.dll" in texto or "failed to load dynlib" in texto:
                        motivo = ("O executavel nao encontrou a biblioteca ViGEmClient.dll. "
                                  "Gere o EXE com o criar_exe.bat atualizado.")
                    elif "vigem_error_bus_not_found" in texto or "0xe0000001" in texto:
                        motivo = "O driver ViGEmBus nao foi localizado pelo Windows."
                    else:
                        motivo = "Nao foi possivel criar o controle Xbox 360 virtual."
                    raise RuntimeError(f"{motivo} Detalhes: {detalhe}") from exc
            self.mode = "virtual" if pad else "test"
            self.virtual_on = pad is not None
            self.events.put(("active", output))
            while not self.stop.is_set():
                try:
                    # Read bloqueante libera CPU, acorda a cada 8 ms para detectar stop.
                    raw = device.read(64, 8)
                except OSError as exc:
                    raise ConnectionError("USB desconectado. Reconecte o controle; a lista será atualizada automaticamente.") from exc
                now = time.monotonic()
                if not raw:
                    if now - last_rx > 0.65 and self.connected:
                        self.connected = False
                        self.state = self.virtual_state = None
                        self.fps = 0.0
                        self.interval_ms = None
                        count = 0
                        last_sample = now
                        if pad:
                            pad.reset()
                            pad.update()
                            last_sent = None
                        self.events.put(("silent", None))
                    if now - last_rx > 3.0:
                        raise ConnectionError("Controle sem resposta por 3 segundos. Verifique o cabo USB.")
                    continue
                try:
                    state = parse_report(raw, self.deadzone)
                except ValueError as exc:
                    rejected += 1
                    if rejected >= 16:
                        raise ValueError(str(exc)) from exc
                    continue
                rejected = 0
                last_rx = now
                if not self.connected:
                    self.connected = True
                    self.events.put(("receiving", None))
                count += 1
                if now - last_sample >= 1.0:
                    elapsed = now - last_sample
                    self.fps = count / elapsed
                    # A media do periodo HID e derivada da frequencia observada.
                    # Nao mede a latencia total entre o controle e o jogo.
                    self.interval_ms = 1000.0 / self.fps if self.fps > 0 else None
                    last_sample, count = now, 0
                self.report_time = now
                self.state = state
                pending_virtual = state_for_virtual(state)
                if pad is not None:
                    # Sem throttle nem espera artificial: baixo input lag; relatórios
                    # identicos sao eliminados, inclusive as atualizacoes de IMU.
                    if last_sent != pending_virtual:
                        send_pad(pad, pending_virtual)
                        last_sent = pending_virtual
                self.virtual_state = pending_virtual if pad else None
        except ConnectionError as exc:
            self.events.put(("disconnected", str(exc)))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            if pad is not None:
                try:
                    pad.reset()
                    pad.update()
                except Exception:
                    pass
                del pad
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass
            self.mode = "idle"
            self.connected = self.virtual_on = False
            self.state = self.virtual_state = None
            self.fps = 0.0
            self.interval_ms = None
            self.events.put(("stopped", None))


class HidHide:
    """Consulta e edita APENAS a lista de HID selecionados via CLI oficial."""
    def __init__(self):
        self.cli = None
        for root in (os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramFiles(x86)")):
            if not root:
                continue
            for sub in ("", "x64"):
                p = Path(root) / "Nefarius Software Solutions" / "HidHide" / sub / "HidHideCLI.exe"
                if p.is_file():
                    self.cli = str(p)
                    break
            if self.cli:
                break

    def cmd(self, *args: str) -> str:
        if not self.cli:
            raise RuntimeError("HidHide nao instalado. Use o link oficial para instalar e reinicie o Windows.")
        done = subprocess.run(
            [self.cli, *args], capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        def decode(buf):
            if buf[:2] in (b"\xff\xfe", b"\xfe\xff"):
                return buf.decode("utf-16").strip()
            try:
                return buf.decode("utf-8-sig").strip()
            except UnicodeDecodeError:
                return buf.decode("mbcs", errors="replace").strip()
        out, err = decode(done.stdout), decode(done.stderr)
        if done.returncode:
            raise RuntimeError((err or out or "HidHideCLI falhou")[:500])
        return out

    def all_pads(self) -> list[dict]:
        output = self.cmd("--dev-gaming")
        containers = json.loads(output)
        devices = []
        seen = set()
        for group in containers:
            for item in group.get("devices", []):
                node = item.get("deviceInstancePath", "")
                if not item.get("present") or not node.upper().startswith("HID\\"):
                    continue
                # Nunca mostrar teclado ou mouse no assistente.
                names = " ".join(str(item.get(k, "")) for k in ("product", "description", "vendor"))
                likely = ("controller" in names.lower() or "gamepad" in names.lower()
                          or "VID_054C" in node.upper() or "dualshock" in names.lower()
                          or "ps4" in names.lower())
                if likely and node not in seen:
                    devices.append(item)
                    seen.add(node)
        return devices

    @staticmethod
    def app_paths() -> list[str]:
        # sys.executable = pythonw.exe ao executar .pyw; = DS4Bridge.exe se empacotado.
        return [str(Path(sys.executable).resolve())]

    def status(self, node: str | None = None) -> tuple[bool, bool]:
        result = self.cmd("--cloak-state", "--dev-list")
        cloaked = "--cloak-on" in result
        if not node:
            return cloaked, False
        hidden = any(node.casefold() in line.casefold() for line in result.splitlines()
                     if line.strip().startswith("--dev-hide"))
        return cloaked, hidden

    def set_hidden(self, node: str, hide: bool) -> tuple[bool, bool]:
        if not re.match(r"^HID\\[\w&{}\-\\]+$", node, flags=re.I):
            raise ValueError("Caminho de instancia HID invalido. Nenhum dispositivo foi alterado.")
        if "VID_045E" in node.upper():
            raise ValueError("O Xbox virtual nao pode ser ocultado por este assistente.")
        if hide:
            if "--inv-on" in self.cmd("--inv-state"):
                raise RuntimeError("Desative 'Inverse application cloak' no HidHide primeiro.")
            args = []
            for executable in self.app_paths():
                args += ["--app-reg", executable]
            args += ["--dev-hide", node, "--cloak-on"]
            self.cmd(*args)
        else:
            # Desfaz somente a instancia selecionada, sem desligar ocultacoes de outros apps.
            self.cmd("--dev-unhide", node)
        cloak_on, listed = self.status(node)
        if listed != hide or (hide and not cloak_on):
            raise RuntimeError("Nao foi possivel validar a mudanca no HidHide.")
        return cloak_on, listed


def name_for(d: dict, idx: int) -> str:
    name = d.get("product_string") or "Controle PS4 compativel"
    return f"{idx + 1:02d}  ·  {name}  [{d.get('vendor_id', 0):04X}:{d.get('product_id', 0):04X}]"



_CONTROLLER_FONT_CACHE = {}

def render_controller(state: dict | None, width: int, height: int) -> Image.Image:
    """Ilustração vetorial antialias do DS4, independente do sistema de interface."""
    state = state or {"buttons": 0, "left": (0., 0.), "right": (0., 0.),
                      "lt": 0, "rt": 0, "touchpad": False}
    width, height = max(1, width), max(1, height)
    factor = min(width / 900, height / 380)
    # Desenha em 2x e reduz por Lanczos: curvas e letras sem serrilhado.
    scale = factor * 2
    ox, oy = (width * 2 - 900 * scale) / 2, (height * 2 - 380 * scale) / 2
    img = Image.new("RGB", (width*2, height*2), PANEL)
    d = ImageDraw.Draw(img)

    def xy(x, y):
        return round(ox + x*scale), round(oy + y*scale)

    def box(x1, y1, x2, y2):
        return (*xy(x1, y1), *xy(x2, y2))

    def line(coords, fill, thick=2, joint="curve"):
        d.line([xy(x,y) for x,y in coords], fill=fill, width=max(1, round(thick*scale)), joint=joint)

    def ellipse(x, y, radius, fill, outline=None, thick=1):
        d.ellipse(box(x-radius,y-radius,x+radius,y+radius), fill=fill, outline=outline,
                  width=max(1,round(thick*scale)))

    def rounded(x1,y1,x2,y2,rad,fill,outline=None,thick=1):
        d.rounded_rectangle(box(x1,y1,x2,y2),radius=max(1,round(rad*scale)),fill=fill,
                            outline=outline, width=max(1,round(thick*scale)))

    font_cache=_CONTROLLER_FONT_CACHE
    def font(size, bold=False):
        key=(size,bold)
        if key not in font_cache:
            files=([r"C:\Windows\Fonts\segoeuib.ttf",r"C:\Windows\Fonts\arialbd.ttf"] if bold
                   else [r"C:\Windows\Fonts\segoeui.ttf",r"C:\Windows\Fonts\arial.ttf"])
            files.append("/usr/share/fonts/truetype/dejavu/DejaVuSans"+("-Bold" if bold else "")+".ttf")
            for path in files:
                try:
                    font_cache[key]=ImageFont.truetype(path,max(8,round(size*scale)))
                    break
                except (OSError, ValueError):
                    continue
            else:
                font_cache[key]=ImageFont.load_default()
        return font_cache[key]

    def label(x,y,s,color=TEXT,size=12,bold=True,anchor="mm"):
        d.text(xy(x,y),s,fill=color,font=font(size,bold),anchor=anchor)

    def cubic(p0,p1,p2,p3,steps=16):
        out=[]
        for i in range(1,steps+1):
            t=i/steps;v=1-t
            out.append((v**3*p0[0]+3*v*v*t*p1[0]+3*v*t*t*p2[0]+t**3*p3[0],
                        v**3*p0[1]+3*v*v*t*p1[1]+3*v*t*t*p2[1]+t**3*p3[1]))
        return out

    def curve_polygon(begin, *segments):
        points=[begin]; end=begin
        for c1,c2,p3 in segments:
            points.extend(cubic(end,c1,c2,p3))
            end=p3
        return [xy(*v) for v in points]

    bits=state["buttons"]
    active=lambda mask: bool(bits & mask)
    on="#55e5d3"
    on_soft="#adfff0"

    # Profundidade / sombra, mantendo a forma simétrica de um DualShock 4.
    shell_args=(
        ((282,100),(309,114),(350,123)),
        ((392,134),(413,127),(450,127)),
        ((487,127),(508,134),(550,123)),
        ((591,114),(618,100),(667,106)),
        ((700,118),(718,163),(752,242)),
        ((782,308),(778,340),(749,344)),
        ((713,355),(661,325),(632,286)),
        ((605,255),(578,261),(545,274)),
        ((507,289),(481,292),(450,293)),
        ((419,292),(393,289),(355,274)),
        ((322,261),(295,255),(268,286)),
        ((239,325),(187,355),(151,344)),
        ((122,340),(118,308),(148,242)),
        ((182,163),(200,118),(233,106)),
    )
    shape=curve_polygon((233,106),*shell_args)
    shadow=[(x,y+round(8*scale)) for x,y in shape]
    d.polygon(shadow, fill="#0b1420")
    d.polygon(shape, fill="#1b2b3f")
    d.line(shape+[shape[0]], fill="#526b83",width=max(1,round(2.6*scale)),joint="curve")
    # Topo / borda interna da placa, alças e textura discreta.
    line([(225,123),(263,119),(316,142),(450,153),(584,142),(637,119),(675,123)],"#2c465e",2)
    line([(173,243),(174,292),(185,316)],"#304960",2)
    line([(727,243),(726,292),(715,316)],"#304960",2)
    rounded(372,134,528,204,13,"#0d1a2a","#58718c",1.8)
    rounded(383,144,517,194,8,"#132337","#263d53",1)
    line([(393,154),(507,154)],"#233c53",1.1)
    label(450,172,"TOUCHPAD",MUTED,11,True)
    if state["touchpad"]:
        rounded(377,139,523,199,11,"#1a5556",on,2.7)
        label(450,170,"TOUCHPAD",on_soft,11,True)

    # Gatilhos analógicos com preenchimento proporcional.
    for x, trigger, shoulder_bit, left in ((272,"lt",0x0100,True),(628,"rt",0x0200,False)):
        pct=max(0,min(1,state[trigger]/255))
        rounded(x-50,32,x+50,65,10,"#152437","#3d566f",1.4)
        if pct:
            rounded(x-47,35,x-47+94*pct,62,7,"#3eb9ac")
        label(x,49,"L2" if left else "R2",on_soft if pct>0.1 else TEXT,12)
        pressed=active(shoulder_bit)
        rounded(x-57,81,x+57,109,11,"#2c8d86" if pressed else "#22364b",
                on if pressed else "#4e6881",1.8)
        label(x,95,"L1" if left else "R1", "#081923" if pressed else TEXT,12)

    # Botões Share / Options integrados ao corpo.
    for x,text_value,mask in ((342,"SHARE",0x0020),(557,"OPTIONS",0x0010)):
        pressed=active(mask)
        rounded(x-20,163,x+20,184,8,"#347f7d" if pressed else "#30445c",
                on if pressed else "#52677c",1.3)
        label(x,174,"••" if pressed else "•", "#07131d" if pressed else "#b9c8d7",13,True)
        label(x,194,text_value, on if pressed else MUTED,10,True)

    # Cruzeta com geometria em cruz e setas iluminadas.
    dpad=[(250,164,"up",0x0001),(250,238,"down",0x0002),
          (213,201,"left",0x0004),(287,201,"right",0x0008)]
    for x,y,direction,mask in dpad:
        pressed=active(mask)
        rounded(x-21,y-21,x+21,y+21,8,"#3ab0a7" if pressed else "#293c52",
                on if pressed else "#455b70",1.6)
        if direction=="up": pts=[(x,y-9),(x-9,y+5),(x+9,y+5)]
        elif direction=="down": pts=[(x,y+9),(x-9,y-5),(x+9,y-5)]
        elif direction=="left": pts=[(x-9,y),(x+5,y-9),(x+5,y+9)]
        else: pts=[(x+9,y),(x-5,y-9),(x-5,y+9)]
        d.polygon([xy(a,b) for a,b in pts],fill="#082029" if pressed else "#b9cfe0")

    # Botões frontais: símbolos PS geométricos; não dependem da fonte instalada.
    buttons=((650,160,"triangle",0x8000,"#83c8a7"),
             (689,199,"circle",0x2000,"#e5a0a8"),
             (650,238,"cross",0x1000,"#9ebbea"),
             (611,199,"square",0x4000,"#d4a9e0"))
    for x,y,kind,mask,color in buttons:
        pressed=active(mask)
        ellipse(x,y,26,"#43baa9" if pressed else "#293c51",on if pressed else "#526b83",2)
        sym="#07202a" if pressed else color
        if kind=="triangle":
            line([(x,y-11),(x-11,y+9),(x+11,y+9),(x,y-11)],sym,2.3)
        elif kind=="circle":
            ellipse(x,y,10,None,sym,2.4)
        elif kind=="cross":
            line([(x-9,y-9),(x+9,y+9)],sym,2.5)
            line([(x+9,y-9),(x-9,y+9)],sym,2.5)
        else:
            rounded(x-10,y-10,x+10,y+10,1,None,sym,2.3)

    # Sticks analógicos: aro mecânico + tampa que acompanha o movimento.
    for x,y,key,mask,label_name in ((345,261,"left",0x0040,"L3"),
                                      (555,261,"right",0x0080,"R3")):
        pressed=active(mask)
        ellipse(x,y,42,"#0b1727",on if pressed else "#4e6a80",2.4)
        ellipse(x,y,35,"#17293e","#2b485d",1.5)
        vx,vy=state[key]
        px=x+min(1,max(-1,vx))*16
        py=y-min(1,max(-1,vy))*16
        ellipse(px,py+3,27,"#0b1827")
        ellipse(px,py,27,"#528b90" if pressed else "#385671",on if pressed else "#67859b",1.6)
        ellipse(px-4,py-4,19,"#58bbb2" if pressed else "#526e88")
        ellipse(px-6,py-7,10,"#75d7cf" if pressed else "#6c879e")
        label(x,y+53,label_name,on if pressed else MUTED,11,True)

    # Botão PS é mostrado, mas não encaminhado para o Guide/Game Bar.
    pressed=active(0x0400)
    ellipse(450,258,20,"#368d84" if pressed else "#263e55",on if pressed else "#587085",1.7)
    label(450,258,"PS","#0a1e24" if pressed else TEXT,11,True)

    return img.resize((width,height),Image.Resampling.LANCZOS)

class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title(f"DS4 Bridge {VERSION}  |  PS4 → Xbox 360")
        self.geometry("1160x810")
        self.minsize(1000, 720)
        self.configure(fg_color=BG)
        self.bridge = Bridge()
        self.hiding = HidHide()
        self.devices: list[dict] = []
        self.selected = ""
        self.probed: set[str] = set()
        self.gui_last = None
        self.scanning = False
        self.selected_path = None
        self.shutdown = False
        self.warning = False
        self.vars = {"deadzone": ctk.DoubleVar(value=2.0)}
        self.make_ui()
        self.after(150, self.scan_tick)
        self.after(50, self.refresh)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def title_label(self, parent, text, small=False):
        return ctk.CTkLabel(parent, text=text, font=(FONT, 13 if small else 17, "bold"),
                            text_color=TEXT, anchor="w")

    def text_label(self, parent, text, color=MUTED, size=12, wrap=280):
        return ctk.CTkLabel(parent, text=text, font=(FONT, size), text_color=color,
                            justify="left", anchor="w", wraplength=wrap)

    def button(self, parent, text, cmd, primary=False, height=38):
        return ctk.CTkButton(parent, text=text, command=cmd, height=height, corner_radius=10,
            font=(FONT, 12, "bold"), fg_color=CYAN if primary else PANEL_LIGHT,
            hover_color="#86f6df" if primary else "#273b52",
            text_color=BG if primary else TEXT, border_width=0)

    def card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=15, border_width=1,
                            border_color=BORDER, **kw)

    def make_ui(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=26, pady=(23, 20))
        ctk.CTkLabel(top, text="◈", font=(FONT, 30, "bold"), text_color=CYAN).pack(side="left", padx=(0, 12))
        title = ctk.CTkFrame(top, fg_color="transparent")
        title.pack(side="left")
        ctk.CTkLabel(title, text="DS4 BRIDGE", font=(FONT, 27, "bold"), text_color=TEXT).pack(anchor="w")
        self.text_label(title, "PS4 USB  /  XINPUT XBOX 360   •   ALTA PRECISÃO", size=10).pack(anchor="w")
        self.version = ctk.CTkLabel(top, text=f"v{VERSION}   •   WINDOWS", font=(FONT, 11, "bold"),
                                    text_color=MUTED)
        self.version.pack(side="right")

        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=26, pady=(0, 12))
        outer.grid_columnconfigure(0, weight=0, minsize=328)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        sidebar = ctk.CTkScrollableFrame(outer, width=316, fg_color="transparent",
                                         scrollbar_button_color=BORDER, scrollbar_button_hover_color=CYAN)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        content = ctk.CTkScrollableFrame(outer, fg_color="transparent",
                                         scrollbar_button_color=BORDER, scrollbar_button_hover_color=CYAN)
        content.grid(row=0, column=1, sticky="nsew")
        self.make_sidebar(sidebar)
        self.make_content(content)
        self.banner_label = ctk.CTkLabel(self, text="Conecte o controle via USB. A detecção é automática.",
            fg_color=PANEL_LIGHT, corner_radius=10, text_color=TEXT,
            font=(FONT, 12), height=47, anchor="w")
        self.banner_label.pack(fill="x", padx=27, pady=(0, 10))
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=28, pady=(0, 12))
        self.text_label(footer, "ViGEmBus mantido  •  PS/Guide bloqueado  •  Sem macros de teclado", size=10).pack(side="left")
        self.text_label(footer, "Mantenha aberto enquanto joga", size=10).pack(side="right")

    def make_sidebar(self, parent):
        box = self.card(parent)
        box.pack(fill="x", pady=(0, 13))
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=17)
        self.title_label(inner, "01   CONEXÃO").pack(anchor="w", pady=(0, 12))
        self.text_label(inner, "Controle físico detectado").pack(anchor="w", pady=(0, 5))
        self.combo = ctk.CTkOptionMenu(inner, values=["Procurando..."], font=(FONT, 11),
            dropdown_font=(FONT, 11), fg_color=PANEL_LIGHT, button_color="#31465f",
            button_hover_color="#426581", text_color=TEXT, dropdown_fg_color=PANEL_LIGHT,
            corner_radius=8, height=38, command=self.choose_device)
        self.combo.pack(fill="x", pady=(0, 10))
        self.rescan = self.button(inner, "Procurar controle", self.scan)
        self.rescan.pack(fill="x", pady=(0, 15))
        self.usb = self.text_label(inner, "●   USB aguardando", size=12)
        self.usb.pack(anchor="w", pady=(0, 6))
        self.xbox = self.text_label(inner, "●   Xbox virtual desligado", size=12)
        self.xbox.pack(anchor="w", pady=(0, 14))
        self.start = self.button(inner, "INICIAR CONVERSÃO", lambda: self.launch(True), primary=True, height=43)
        self.start.pack(fill="x", pady=(0, 9))
        self.start.configure(state="disabled")
        self.test = self.button(inner, "Testar apenas o USB", lambda: self.launch(False))
        self.test.pack(fill="x", pady=(0, 9))
        self.test.configure(state="disabled")
        self.stop = self.button(inner, "Parar conversão", self.stop_bridge)
        self.stop.pack(fill="x")
        self.stop.configure(state="disabled")

        services = self.card(parent)
        services.pack(fill="x", pady=(0, 5))
        svc = ctk.CTkFrame(services, fg_color="transparent")
        svc.pack(fill="x", padx=18, pady=17)
        self.title_label(svc, "02   COMPATIBILIDADE").pack(anchor="w", pady=(0, 12))
        self.button(svc, "Configurar HidHide", self.hidhide_dialog).pack(fill="x", pady=(0, 9))
        self.button(svc, "Testar no Windows", self.joy).pack(fill="x", pady=(0, 9))
        self.button(svc, "Site do driver ViGEmBus", lambda: webbrowser.open(VIGEM_URL)).pack(fill="x")
        self.hide_status = self.text_label(svc, "Ocultação física: verificando...", size=11, wrap=270)
        self.hide_status.pack(anchor="w", pady=(13, 0))

    def make_content(self, parent):
        overview = self.card(parent)
        overview.pack(fill="x", pady=(0, 13))
        inner = ctk.CTkFrame(overview, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=17)
        self.title_label(inner, "VISÃO GERAL   /   MONITOR EM TEMPO REAL").pack(anchor="w", pady=(0, 12))
        badges = ctk.CTkFrame(inner, fg_color="transparent")
        badges.pack(fill="x")
        for col in (0, 1):
            badges.grid_columnconfigure(col, weight=1)
        self.rate = self.metric(badges, 0, "INTERVALO HID / MS", "—")
        self.signal = self.metric(badges, 1, "SAÍDA XINPUT", "OFF")
        self.text_label(inner, "Estimativa: 1000 ÷ relatórios/s. Não é a latência total do jogo.",
                        size=10, wrap=630).pack(anchor="w", pady=(9, 0))
        self.warning_label = self.text_label(inner,
            "Se o jogo alternar entre mouse e controle, configure a ocultação do PS4 físico no HidHide.",
            color=AMBER, size=11, wrap=600)
        self.warning_label.pack(anchor="w", pady=(14, 0))

        monitor = self.card(parent)
        monitor.pack(fill="x", pady=(0, 6))
        mc = ctk.CTkFrame(monitor, fg_color="transparent")
        mc.pack(fill="x", padx=20, pady=16)
        heading = ctk.CTkFrame(mc, fg_color="transparent")
        heading.pack(fill="x", pady=(0, 5))
        self.title_label(heading, "TESTE DO CONTROLE").pack(side="left")
        self.progress_text = ctk.CTkLabel(heading, text="0 / 18 testados", font=(FONT, 11, "bold"),
                                          text_color=CYAN)
        self.progress_text.pack(side="right")
        self.text_label(mc, "Pressione os botões. Os comandos ativos ficam iluminados; analógicos e gatilhos respondem ao movimento.",
                        size=11, wrap=670).pack(anchor="w", pady=(0, 7))
        self.canvas = Canvas(mc, bg=PANEL, height=332, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x", pady=(3, 7))
        self.canvas.bind("<Configure>", lambda e: self.draw(force=True))
        self.last_action = self.text_label(mc, "Aguardando comandos do controle…", color=MUTED, size=11, wrap=670)
        self.last_action.pack(anchor="w", pady=(0, 4))

        adjust = self.card(parent)
        adjust.pack(fill="x", pady=(0, 6))
        ad = ctk.CTkFrame(adjust, fg_color="transparent")
        ad.pack(fill="x", padx=18, pady=16)
        self.title_label(ad, "AJUSTE DOS ANALÓGICOS").pack(anchor="w", pady=(0, 13))
        self.dead_text = self.text_label(ad, "Zona morta radial: 2%", color=TEXT)
        self.dead_text.pack(anchor="w")
        self.slider = ctk.CTkSlider(ad, from_=0, to=20, number_of_steps=20, variable=self.vars["deadzone"],
            progress_color=CYAN, button_color=CYAN, button_hover_color="#a3fff1",
            fg_color=BORDER, command=self.dead_change)
        self.slider.pack(fill="x", pady=(8, 5))
        # Bloqueia a rodinha APENAS neste ajuste, sem afetar o arraste do slider.
        # CustomTkinter desenha o CTkSlider em um Canvas interno.
        # Interceptar tanto o componente quanto o Canvas evita mudancas por scroll.
        for control in (self.slider, self.slider._canvas):
            for event_name in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                control.bind(event_name, self._ignore_deadzone_wheel, add="+")
        self.text_label(ad, "Padrão: 2%. Ajuste somente arrastando o controle deslizante.", size=11).pack(anchor="w")


    def metric(self, parent, column, heading, initial):
        frame = ctk.CTkFrame(parent, fg_color=PANEL_LIGHT, corner_radius=10)
        frame.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 5, 5 if column < 2 else 0))
        ctk.CTkLabel(frame, text=heading, text_color=MUTED,
            font=(FONT, 10, "bold")).pack(anchor="w", padx=13, pady=(10, 0))
        data = ctk.CTkLabel(frame, text=initial, text_color=TEXT, font=(FONT, 23, "bold"))
        data.pack(anchor="w", padx=13, pady=(0, 10))
        return data

    def banner(self, value: str, error=False):
        self.banner_label.configure(text="  " + value, text_color=RED if error else TEXT,
                                    fg_color="#38212e" if error else PANEL_LIGHT)

    @staticmethod
    def _ignore_deadzone_wheel(_event):
        """Impede que o scroll do mouse altere a zona morta."""
        return "break"

    def dead_change(self, value: float):
        value = round(value)
        self.bridge.deadzone = value / 100.0
        self.dead_text.configure(text=f"Zona morta radial: {value}%")

    def choose_device(self, label: str):
        self.selected = label
        for i, d in enumerate(self.devices):
            if name_for(d, i) == label:
                self.selected_path = d["path"]
                break

    def scan_tick(self):
        if self.shutdown:
            return
        self.scan()
        self.after(2500, self.scan_tick)

    def scan(self):
        # A enumeração HID pode bloquear: nunca rodar na thread da interface.
        if self.shutdown or self.scanning or (self.bridge.thread and self.bridge.thread.is_alive()):
            return
        self.scanning = True
        def work():
            try:
                import hid
                seen=set(); found=[]
                for d in hid.enumerate():
                    path=d.get("path")
                    if path and path not in seen and maybe_controller(d):
                        seen.add(path)
                        found.append(d)
                self.bridge.events.put(("scan_result", found))
            except Exception as exc:
                self.bridge.events.put(("scan_error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def device_result(self, found):
        self.scanning=False
        old_path=self.selected_path
        old_paths=[d["path"] for d in self.devices]
        new_paths=[d["path"] for d in found]
        self.devices=found
        if old_path not in new_paths:
            self.selected_path=new_paths[0] if new_paths else None
        names=[name_for(d,i) for i,d in enumerate(found)]
        options=names or ["Nenhum controle conectado"]
        self.combo.configure(values=options)
        chosen=next((name_for(d,i) for i,d in enumerate(found) if d["path"]==self.selected_path),options[0])
        if self.combo.get()!=chosen:
            self.combo.set(chosen)
        self.selected=chosen if found else ""
        active=bool(self.bridge.thread and self.bridge.thread.is_alive())
        if not active:
            self.start.configure(state="normal" if found else "disabled")
            self.test.configure(state="normal" if found else "disabled")
            self.usb.configure(text="●   PS4 USB detectado automaticamente" if found else "●   Aguardando controle USB",
                               text_color=GREEN if found else MUTED)
            if new_paths!=old_paths:
                self.banner("Controle detectado. Você já pode iniciar a conversão." if found else
                            "Conecte o controle via USB. Ele aparecerá automaticamente.")
        self.hide_status.configure(text="●   HidHide disponível. Confira a ocultação do PS4." if self.hiding.cli else
                                  "●   HidHide não instalado. Pode haver entrada duplicada no jogo.",
                                   text_color=CYAN if self.hiding.cli else AMBER)

    def launch(self, virtual: bool):
        if self.bridge.thread and self.bridge.thread.is_alive():
            return
        if not self.selected_path or not any(d["path"]==self.selected_path for d in self.devices):
            self.banner("Aguardando controle USB. Ele deve aparecer automaticamente.", True)
            self.scan()
            return
        self.probed.clear()
        self.warning=False
        self.gui_last=None
        self.bridge.launch(self.selected_path, virtual)
        for widget in (self.start, self.test, self.rescan, self.combo):
            widget.configure(state="disabled")
        self.stop.configure(state="normal")
        self.banner("Abrindo dispositivo USB e preparando a saída..." if virtual else "Preparando teste USB...")

    def stop_bridge(self):
        self.bridge.stop.set()
        self.stop.configure(state="disabled")
        self.banner("Desativando Xbox virtual e liberando os comandos...")

    def joy(self):
        try:
            subprocess.Popen(["control.exe", "joy.cpl"])
        except Exception as exc:
            self.banner(f"Não foi possível abrir o teste do Windows: {exc}", True)

    def draw(self, force=False):
        if not self.canvas.winfo_exists():
            return
        w=max(2, self.canvas.winfo_width())
        h=max(2, self.canvas.winfo_height())
        state=self.bridge.state
        current=(state,w,h)
        if not force and current==self.gui_last:
            return
        self.gui_last=current
        picture=render_controller(state,w,h)
        self.controller_picture=ImageTk.PhotoImage(picture, master=self.canvas)
        self.canvas.delete("all")
        self.canvas.create_image(0,0,anchor="nw",image=self.controller_picture)

    def hidhide_dialog(self):
        if self.bridge.thread and self.bridge.thread.is_alive():
            self.banner("Pare a conversão antes de alterar o HidHide.", True)
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title("DS4 Bridge  |  Configurar HidHide")
        dialog.geometry("850x560")
        dialog.minsize(750, 510)
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        dialog.grab_set()
        body = ctk.CTkFrame(dialog, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=25, pady=22)
        self.title_label(body, "OCULTAÇÃO DO CONTROLE FÍSICO").pack(anchor="w", pady=(0, 9))
        self.text_label(body,
            "O HidHide impede que o jogo veja o PS4 físico e deixa o DS4 Bridge lendo o controle. "
            "O Xbox 360 virtual continua visível. É necessário instalar o HidHide uma vez.",
            size=12, wrap=780).pack(anchor="w", pady=(0, 16))
        ctk.CTkLabel(body, text="Selecione o dispositivo HID correspondente ao seu PS4",
            font=(FONT, 12, "bold"), text_color=TEXT).pack(anchor="w", pady=(0, 7))
        choices = ctk.CTkOptionMenu(body, values=["Clique em Procurar dispositivos"],
            fg_color=PANEL_LIGHT, button_color=BORDER, width=780, height=38,
            dynamic_resizing=False, font=(FONT, 11), dropdown_font=(FONT, 11))
        choices.pack(fill="x")
        found = []
        status = ctk.CTkLabel(body, text="HidHide: " + ("encontrado" if self.hiding.cli else "não instalado"),
            justify="left", anchor="w", fg_color=PANEL, corner_radius=9,
            wraplength=760, text_color=CYAN if self.hiding.cli else AMBER,
            font=(FONT, 12), height=69)
        status.pack(fill="x", pady=(14, 12))

        def async_work(operation):
            # Leitura de widgets Tk so na thread principal, antes de criar o worker.
            selected_node = None
            if operation != "scan":
                try:
                    i = int(choices.get().split("  ·  ")[0]) - 1
                    selected_node = found[i]["deviceInstancePath"]
                    if i < 0:
                        raise IndexError
                except (ValueError, IndexError, KeyError):
                    status.configure(text="Selecione um controle HID na lista antes de continuar.", text_color=RED)
                    return
            def worker():
                try:
                    if operation == "scan":
                        result = self.hiding.all_pads()
                    else:
                        result = self.hiding.set_hidden(selected_node, operation == "hide")
                    self.bridge.events.put(("hide_"+operation, (dialog, status, choices, found, result)))
                except Exception as exc:
                    self.bridge.events.put(("hide_error", (dialog, status, str(exc))))
            status.configure(text="Consultando HidHide...", text_color=CYAN)
            threading.Thread(target=worker, daemon=True).start()

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 14))
        self.button(actions, "Procurar dispositivos", lambda: async_work("scan")).pack(side="left", padx=(0, 8))
        self.button(actions, "Ocultar PS4", lambda: async_work("hide"), primary=True).pack(side="left", padx=(0, 8))
        self.button(actions, "Mostrar PS4", lambda: async_work("show")).pack(side="left")
        if not self.hiding.cli:
            self.button(body, "Baixar HidHide oficial", lambda: webbrowser.open(HIDHIDE_URL)).pack(anchor="w", pady=(0, 11))
        self.text_label(body,
            "IMPORTANTE: desconecte e reconecte o cabo USB após ocultar ou mostrar. "
            "Configure com o jogo fechado. A ocultação permanece mesmo quando o app fecha. "
            "Nunca selecione mouse, teclado ou o Xbox virtual. Se trocar o EXE do Bridge, "
            "será necessário autorizar o novo executável no HidHide.", wrap=780, size=11).pack(anchor="w")
        self.button(body, "Concluir", dialog.destroy).pack(side="bottom", anchor="e", pady=(12, 0))

    def event(self, name, data):
        if name == "scan_result":
            self.device_result(data)
            return
        if name == "scan_error":
            self.scanning=False
            self.banner("Erro na detecção USB: " + str(data), True)
            return
        if name.startswith("hide_"):
            if name == "hide_error":
                dialog, label, msg = data
                if dialog.winfo_exists():
                    label.configure(text=msg, text_color=RED)
                self.banner("HidHide: " + msg, True)
                return
            dialog, label, choices, found, result = data
            if not dialog.winfo_exists():
                return
            if name == "hide_scan":
                found[:] = result
                options = [f"{i+1:02d}  ·  {d.get('product') or d.get('description') or 'Gamepad'}  ·  {d['deviceInstancePath']}"
                           for i, d in enumerate(found)]
                choices.configure(values=options or ["Nenhum gamepad encontrado"])
                choices.set(options[0] if options else "Nenhum gamepad encontrado")
                label.configure(text=f"Encontrados {len(found)} HID(s) de controle. Confirme o VID/PID do PS4 antes de ocultar.",
                                text_color=CYAN)
            else:
                cloaked, listed = result
                label.configure(text=("PS4 incluído na lista do HidHide. Reconecte o USB; a detecção é automática."
                         if listed else "PS4 removido da lista do HidHide. Reconecte o USB."), text_color=GREEN)
                self.hide_status.configure(text="●   HidHide: controle na lista de ocultação" if listed else
                                                "●   HidHide: controle removido da lista", text_color=GREEN if listed else AMBER)
                self.banner("Ocultação salva. Replugue o controle para a alteração ter efeito.")
            return
        if name == "active":
            self.xbox.configure(text="●   Xbox virtual criado" if data else "●   Modo apenas teste USB",
                                text_color=GREEN if data else AMBER)
            self.signal.configure(text="ON" if data else "TESTE", text_color=GREEN if data else AMBER)
            self.banner("Xbox criado. Confira HidHide e só então abra o jogo." if data else "Teste USB iniciado sem criar Xbox virtual.")
        elif name == "receiving":
            self.usb.configure(text="●   USB recebendo dados", text_color=GREEN)
        elif name == "silent":
            self.usb.configure(text="●   Sem dados USB", text_color=AMBER)
            self.banner("USB parou de enviar relatórios. Comandos liberados; aguardando até 3 s.", True)
        elif name in ("error", "disconnected"):
            self.warning = True
            self.usb.configure(text="●   Falha / desconectado", text_color=RED)
            self.banner(data, True)
            if name == "disconnected" and not self.shutdown:
                self.bell()
                messagebox.showwarning("DS4 Bridge — controle desconectado", data, parent=self)
        elif name == "stopped":
            self.xbox.configure(text="●   Xbox virtual desligado", text_color=MUTED)
            self.signal.configure(text="OFF", text_color=TEXT)
            for widget in (self.rescan, self.combo):
                widget.configure(state="normal")
            self.start.configure(state="normal" if self.selected_path else "disabled")
            self.test.configure(state="normal" if self.selected_path else "disabled")
            self.stop.configure(state="disabled")
            self.after(100, self.scan)
            if not self.warning:
                self.usb.configure(text="●   Leitura USB parada", text_color=MUTED)
                self.banner("Parado. O Xbox virtual foi removido.")

    def refresh(self):
        for _ in range(25):
            try:
                name, data=self.bridge.events.get_nowait()
            except queue.Empty:
                break
            if not self.shutdown:
                self.event(name, data)
        state=self.bridge.state
        self.rate.configure(text=f"{self.bridge.interval_ms:.1f} ms"
                            if state and self.bridge.interval_ms is not None else "—")
        if state:
            pressed=[name for name,bit in KEYS if state["buttons"] & bit]
            self.probed.update(name for name,bit in KEYS if state["buttons"] & bit)
            if state["touchpad"]:
                pressed.append("TOUCHPAD")
                self.probed.add("TOUCHPAD")
            if state["lt"]>=12:
                pressed.append("L2")
                self.probed.add("L2")
            if state["rt"]>=12:
                pressed.append("R2")
                self.probed.add("R2")
            self.last_action.configure(text="Pressionado: " + ", ".join(pressed[:9]) if pressed else
                                       "Sem botões pressionados  •  Mova os analógicos para testar.",
                                       text_color=TEXT if pressed else MUTED)
        else:
            self.last_action.configure(text="Aguardando comandos do controle…",text_color=MUTED)
        self.progress_text.configure(text=f"{len(self.probed)} / 18 testados")
        self.draw()
        if self.shutdown and (self.bridge.thread is None or not self.bridge.thread.is_alive()):
            self.destroy()
            return
        self.after(50, self.refresh)

    def close(self):
        self.shutdown = True
        self.bridge.stop.set()
        if not self.bridge.thread or not self.bridge.thread.is_alive():
            self.destroy()


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("DS4 Bridge foi desenvolvido exclusivamente para Windows.")
    try:
        App().mainloop()
    except Exception as exc:
        exibir_erro_inicio(exc)
        raise SystemExit(1) from exc
