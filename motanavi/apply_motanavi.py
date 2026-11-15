#!/usr/bin/env python3
"""MotaNavi: переделывает репозиторий Ghostgram в MotaNavi.

Запускается из корня репозитория:   python3 motanavi/apply_motanavi.py
Можно запускать много раз: уже сделанные правки пропускаются.
Если какое-то место в коде не найдено, скрипт останавливается и пишет, какое.
"""
import glob
import os
import subprocess
import sys

ROOT = os.getcwd()
BRAND_OLD = "Ghostgram"
BRAND_NEW = "MotaNavi"

# ---------------------------------------------------------------------------
# ВАШИ ССЫЛКИ. Поменяйте три адреса на свои (канал, чат, форум).
# ---------------------------------------------------------------------------
LINKS = {
    "channel": "ghostgrama",
    "chat": "ghostgramchat",
    "forum": "ghostgramforum",
}


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as f:
        f.write(text)


def replace_once(path, old, new, marker=None):
    text = read(path)
    if (marker or new) in text:
        print("уже сделано:", path)
        return
    if text.count(old) != 1:
        sys.exit("ОШИБКА: в файле %s не найдено нужное место (найдено %d раз). "
                 "Скопируйте это сообщение и отправьте Claude." % (path, text.count(old)))
    write(path, text.replace(old, new))
    print("исправлено:", path)


# 1. Название в текстах меню (все языки) и перегенерация строк ----------------
for path in glob.glob(os.path.join(ROOT, "Ghostgram/Strings/*/*.json")):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if BRAND_OLD in text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(BRAND_OLD, BRAND_NEW))
subprocess.check_call([sys.executable, "Ghostgram/Strings/generate.py"], cwd=ROOT)
subprocess.call([sys.executable, "Ghostgram/Strings/check.py"], cwd=ROOT)  # только проверка, не критично

# 2. Тексты разрешений (InfoPlist) ----------------------------------------------
for path in glob.glob(os.path.join(ROOT, "Telegram/Telegram-iOS/*.lproj/InfoPlist.strings")):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if BRAND_OLD in text:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(BRAND_OLD, BRAND_NEW))

# 3. Имя приложения под иконкой --------------------------------------------------
build = read("Telegram/BUILD")
build = build.replace("<string>Ghostgram</string> <!-- GHOST: app name -->",
                      "<string>MotaNavi</string> <!-- GHOST: app name -->")
write("Telegram/BUILD", build)
print("имя приложения: MotaNavi")

# 4. Ссылки на канал / чат / форум в настройках мода ------------------------------
menu = "Ghostgram/GGSettingsUI/Sources/Screens/GGMenuScreen.swift"
text = read(menu)
start = text.index("let ggMenuLinks")
end = text.index("func ggMenuLinkTitle")
new_links = (
    'let ggMenuLinks: [(id: String, url: String, username: String, icon: GGMenuIcon)] = [\n'
    '    (id: "channel", url: "https://t.me/%(channel)s", username: "@%(channel)s", icon: .bundle("Chat/Context Menu/Channels")),\n'
    '    (id: "chat", url: "https://t.me/%(chat)s", username: "@%(chat)s", icon: .bundle("Chat/Context Menu/Groups")),\n'
    '    (id: "forum", url: "https://t.me/%(forum)s", username: "@%(forum)s", icon: .bundle("Chat/Context Menu/Replies"))\n'
    ']\n\n' % LINKS
)
write(menu, text[:start] + new_links + text[end:])
print("ссылки:", LINKS)

# 5. Выбор микрофона в звонке ------------------------------------------------------
MIC = '''import Foundation
import AVFoundation

// MOTANAVI: выбор микрофона во время звонка.
// Compiled into TelegramAudio (filegroup //Ghostgram/Features/Voice:TelegramAudioPoints).

public enum GGCallMicrophoneMode: Int {
    /// Как решает система (поведение Telegram по умолчанию).
    case automatic = 0
    /// Говорить в микрофон телефона, слушать через то, что выбрано как вывод (например, наушники).
    case phone = 1
    /// Говорить в микрофон гарнитуры / наушников.
    case headset = 2
}

public enum GGCallMicrophone {
    private static let defaultsKey = "motanavi.callMicrophoneMode"
    private static var didOverride = false

    public static var mode: GGCallMicrophoneMode {
        get {
            return GGCallMicrophoneMode(rawValue: UserDefaults.standard.integer(forKey: GGCallMicrophone.defaultsKey)) ?? .automatic
        }
        set {
            UserDefaults.standard.set(newValue.rawValue, forKey: GGCallMicrophone.defaultsKey)
        }
    }

    /// Применяет выбранный режим к текущей аудио-сессии. Безопасно вызывать много раз.
    public static func apply() {
        let session = AVAudioSession.sharedInstance()
        switch GGCallMicrophone.mode {
        case .automatic:
            if GGCallMicrophone.didOverride {
                GGCallMicrophone.didOverride = false
                let _ = try? session.setPreferredInput(nil)
            }
        case .phone:
            guard let builtIn = session.availableInputs?.first(where: { $0.portType == .builtInMic }) else {
                return
            }
            GGCallMicrophone.didOverride = true
            let _ = try? session.setPreferredInput(builtIn)
        case .headset:
            let headsetTypes: [AVAudioSession.Port] = [.headsetMic, .headphones, .bluetoothHFP, .bluetoothA2DP, .bluetoothLE]
            guard let headset = session.availableInputs?.first(where: { headsetTypes.contains($0.portType) }) else {
                return
            }
            GGCallMicrophone.didOverride = true
            let _ = try? session.setPreferredInput(headset)
        }
    }
}
'''
mic_path = "Ghostgram/Features/Voice/Points/TelegramAudio/GGCallMicrophone.swift"
write(mic_path, MIC)
print("создан файл:", mic_path)

audio = "submodules/TelegramAudio/Sources/ManagedAudioSession.swift"
replace_once(
    audio,
    '''        } catch let e {
            managedAudioSessionLog("applyVoiceChatOutputModeInCurrentAudioSession error: \\(e)")
        }
    }
''',
    '''        } catch let e {
            managedAudioSessionLog("applyVoiceChatOutputModeInCurrentAudioSession error: \\(e)")
        }
        // MOTANAVI: the user's microphone choice for calls (GGCallMicrophone)
        GGCallMicrophone.apply()
    }
''',
    marker="// MOTANAVI: the user's microphone choice for calls (GGCallMicrophone)\n        GGCallMicrophone.apply()\n    }")
replace_once(
    audio,
    '''        ggApplyBuiltInMicrophoneIfNeeded(isRecording: type.isRecord, isHeadsetConnected: self.isHeadsetPluggedInValue)
''',
    '''        ggApplyBuiltInMicrophoneIfNeeded(isRecording: type.isRecord, isHeadsetConnected: self.isHeadsetPluggedInValue)
        // MOTANAVI: the user's microphone choice for calls (GGCallMicrophone)
        switch type {
        case .voiceCall, .videoCall:
            GGCallMicrophone.apply()
        default:
            break
        }
''',
    marker="        switch type {\n        case .voiceCall, .videoCall:\n            GGCallMicrophone.apply()")

replace_once(
    "submodules/TelegramCallsUI/Sources/CallController.swift",
    '''                actionSheet.setItemGroups([ActionSheetItemGroup(items: items), ActionSheetItemGroup(items: [
                        ActionSheetButtonItem(title: strongSelf.presentationData.strings.Call_AudioRouteHide, color: .accent, font: .bold, action: { [weak actionSheet] in
                            actionSheet?.dismissAnimated()
                        })
                    ])
                ])
                strongSelf.present(actionSheet, in: .window(.calls))''',
    '''                // MOTANAVI: microphone choice (phone / headset / automatic)
                let isRussian = strongSelf.presentationData.strings.baseLanguageCode == "ru"
                let micOptions: [(GGCallMicrophoneMode, String)] = [
                    (.automatic, isRussian ? "Микрофон: авто" : "Microphone: auto"),
                    (.phone, isRussian ? "Микрофон: телефона" : "Microphone: phone"),
                    (.headset, isRussian ? "Микрофон: наушников" : "Microphone: headset")
                ]
                var micItems: [ActionSheetItem] = []
                for (micMode, micTitle) in micOptions {
                    micItems.append(CallRouteActionSheetItem(title: micTitle, icon: nil, selected: GGCallMicrophone.mode == micMode, action: { [weak actionSheet] in
                        actionSheet?.dismissAnimated()
                        GGCallMicrophone.mode = micMode
                        GGCallMicrophone.apply()
                    }))
                }
                
                actionSheet.setItemGroups([ActionSheetItemGroup(items: items), ActionSheetItemGroup(items: micItems), ActionSheetItemGroup(items: [
                        ActionSheetButtonItem(title: strongSelf.presentationData.strings.Call_AudioRouteHide, color: .accent, font: .bold, action: { [weak actionSheet] in
                            actionSheet?.dismissAnimated()
                        })
                    ])
                ])
                strongSelf.present(actionSheet, in: .window(.calls))''',
    marker="// MOTANAVI: microphone choice (phone / headset / automatic)")

print("\nГОТОВО: MotaNavi применён.")

