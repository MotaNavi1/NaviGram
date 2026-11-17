#!/usr/bin/env python3
"""MotaNavi, часть 2: плагины и раздельный выбор микрофона/звука в звонке.

Запускается из корня репозитория ПОСЛЕ apply_motanavi.py:
    python3 motanavi/apply_part2.py
Можно запускать много раз: уже сделанные правки пропускаются.
"""
import os
import sys

ROOT = os.getcwd()


def write(path, text):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    print("записан файл:", path)


def replace_once(path, old, new, marker):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        text = f.read()
    if marker in text:
        print("уже сделано:", path)
        return
    if text.count(old) != 1:
        sys.exit("ОШИБКА: в файле %s не найдено нужное место (найдено %d раз). "
                 "Скопируйте это сообщение и отправьте Claude." % (path, text.count(old)))
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))
    print("исправлено:", path)

MIC = r'''import Foundation
import AVFoundation

// MOTANAVI: выбор микрофона во время звонка, независимо от того, куда идёт звук.
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
    private static var didOverrideInput = false
    private static var didRemoveHFP = false

    private static let routeObserver: NSObjectProtocol = NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: nil, using: { _ in
        DispatchQueue.main.async {
            GGCallMicrophone.apply()
        }
    })

    public static var mode: GGCallMicrophoneMode {
        get {
            return GGCallMicrophoneMode(rawValue: UserDefaults.standard.integer(forKey: GGCallMicrophone.defaultsKey)) ?? .automatic
        }
        set {
            UserDefaults.standard.set(newValue.rawValue, forKey: GGCallMicrophone.defaultsKey)
        }
    }

    private static var hfpOption: AVAudioSession.CategoryOptions {
        #if canImport(AlarmKit) //Xcode 26
        return .allowBluetoothHFP
        #else
        return .allowBluetooth
        #endif
    }

    private static func isBluetooth(_ port: AVAudioSession.Port) -> Bool {
        return port == .bluetoothA2DP || port == .bluetoothHFP || port == .bluetoothLE
    }

    private static func restoreHFP(_ session: AVAudioSession) {
        guard GGCallMicrophone.didRemoveHFP else {
            return
        }
        GGCallMicrophone.didRemoveHFP = false
        var options = session.categoryOptions
        options.insert(GGCallMicrophone.hfpOption)
        let _ = try? session.setCategory(session.category, mode: session.mode, options: options)
    }

    /// Применяет выбранный режим к текущей аудио-сессии звонка. Безопасно вызывать много раз.
    public static func apply() {
        let _ = GGCallMicrophone.routeObserver
        let session = AVAudioSession.sharedInstance()

        // Только во время звонка: в остальное время ничего не трогаем.
        guard session.mode == .voiceChat || session.mode == .videoChat else {
            GGCallMicrophone.didOverrideInput = false
            GGCallMicrophone.didRemoveHFP = false
            return
        }

        switch GGCallMicrophone.mode {
        case .automatic:
            GGCallMicrophone.restoreHFP(session)
            if GGCallMicrophone.didOverrideInput {
                GGCallMicrophone.didOverrideInput = false
                let _ = try? session.setPreferredInput(nil)
            }
        case .phone:
            // Bluetooth-наушники по умолчанию забирают и микрофон (профиль HFP). Чтобы звук шёл в них,
            // а говорить можно было в телефон, HFP на время выключаем: останется только A2DP.
            let outputIsBluetooth = session.currentRoute.outputs.contains(where: { GGCallMicrophone.isBluetooth($0.portType) })
            if outputIsBluetooth && !GGCallMicrophone.didRemoveHFP {
                var options = session.categoryOptions
                options.remove(GGCallMicrophone.hfpOption)
                options.insert(.allowBluetoothA2DP)
                if (try? session.setCategory(session.category, mode: session.mode, options: options)) != nil {
                    GGCallMicrophone.didRemoveHFP = true
                }
            }
            if session.currentRoute.inputs.first?.portType == .builtInMic {
                return
            }
            guard let builtIn = session.availableInputs?.first(where: { $0.portType == .builtInMic }) else {
                return
            }
            GGCallMicrophone.didOverrideInput = true
            let _ = try? session.setPreferredInput(builtIn)
        case .headset:
            GGCallMicrophone.restoreHFP(session)
            let headsetTypes: [AVAudioSession.Port] = [.headsetMic, .headphones, .bluetoothHFP, .bluetoothA2DP, .bluetoothLE]
            if let current = session.currentRoute.inputs.first, headsetTypes.contains(current.portType) {
                return
            }
            guard let headset = session.availableInputs?.first(where: { headsetTypes.contains($0.portType) }) else {
                return
            }
            GGCallMicrophone.didOverrideInput = true
            let _ = try? session.setPreferredInput(headset)
        }
    }
}
'''

BUILD = r'''load("@build_bazel_rules_swift//swift:swift.bzl", "swift_library")

# Feature module GGPlugins (MotaNavi): JavaScript plugins written by the user.
# May depend on everything below TelegramUI; never on TelegramUI or another GG<Feature> module.
swift_library(
    name = "GGPlugins",
    module_name = "GGPlugins",
    srcs = glob([
        "Sources/**/*.swift",
    ]),
    copts = [
        "-warnings-as-errors",
    ],
    deps = [
        "//Ghostgram/GGCore:GGCore",
        "//Ghostgram/GGHooks:GGHooks",
        "//Ghostgram/GGSettingsUI:GGSettingsUI",
        "//Ghostgram/Features/Shared:GGFeaturesShared",
        "//submodules/SSignalKit/SwiftSignalKit:SwiftSignalKit",
        "//submodules/Postbox:Postbox",
        "//submodules/TelegramCore:TelegramCore",
        "//submodules/AccountContext:AccountContext",
        "//submodules/TelegramPresentationData:TelegramPresentationData",
        "//submodules/Display:Display",
        "//submodules/AsyncDisplayKit:AsyncDisplayKit",
        "//submodules/ItemListUI:ItemListUI",
        "//submodules/PresentationDataUtils:PresentationDataUtils",
        "//submodules/TextFormat:TextFormat",
    ],
    visibility = [
        "//visibility:public",
    ],
)
'''

MANAGER = r'''import Foundation
import JavaScriptCore
import SwiftSignalKit

/// MotaNavi plugins: JavaScript files stored on the device. Every plugin lives in its own
/// JavaScriptCore context, which has no network and no file access: only the `motanavi` object below.
final class GGPluginManager {
    static let shared = GGPluginManager()

    struct Entry: Codable {
        var id: String
        var name: String
        var version: String
        var info: String
        var enabled: Bool
    }

    enum SendOutcome {
        case unchanged
        case cancelled
        case replaced(String)
    }

    enum InstallResult {
        case installed(Entry, updated: Bool)
        case failed(String)
    }

    private(set) var entries: [Entry] = []
    private var contexts: [String: JSContext] = [:]
    private var errors: [String: String] = [:]
    private let changePipe = ValuePipe<Int>()
    private var revision: Int = 0

    var changes: Signal<Int, NoError> {
        return self.changePipe.signal()
    }

    private static var directory: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return base.appendingPathComponent("MotaNavi", isDirectory: true).appendingPathComponent("Plugins", isDirectory: true)
    }

    private static var indexURL: URL {
        return GGPluginManager.directory.appendingPathComponent("index.json")
    }

    private static var logURL: URL {
        return GGPluginManager.directory.appendingPathComponent("plugins.log")
    }

    private static func fileURL(_ id: String) -> URL {
        return GGPluginManager.directory.appendingPathComponent(id + ".js")
    }

    private init() {
        let _ = try? FileManager.default.createDirectory(at: GGPluginManager.directory, withIntermediateDirectories: true)
        if let data = try? Data(contentsOf: GGPluginManager.indexURL), let decoded = try? JSONDecoder().decode([Entry].self, from: data) {
            self.entries = decoded
        }
    }

    // MARK: State

    var hasEnabledPlugins: Bool {
        return self.entries.contains(where: { $0.enabled })
    }

    func isEnabled(_ id: String) -> Bool {
        return self.entries.first(where: { $0.id == id })?.enabled ?? false
    }

    func subtitle(for id: String) -> String {
        guard let entry = self.entries.first(where: { $0.id == id }) else {
            return ""
        }
        var parts: [String] = []
        if !entry.version.isEmpty {
            parts.append("v" + entry.version)
        }
        if !entry.info.isEmpty {
            parts.append(entry.info)
        }
        var text = parts.joined(separator: " · ")
        if let error = self.errors[id] {
            text += (text.isEmpty ? "" : "\n") + "Ошибка: " + error
        }
        return text
    }

    // MARK: Changes

    func setEnabled(_ id: String, _ enabled: Bool) {
        guard let index = self.entries.firstIndex(where: { $0.id == id }) else {
            return
        }
        self.entries[index].enabled = enabled
        if enabled {
            self.errors[id] = nil
        }
        self.commit()
    }

    func remove(_ id: String) {
        self.entries.removeAll(where: { $0.id == id })
        self.contexts[id] = nil
        self.errors[id] = nil
        let _ = try? FileManager.default.removeItem(at: GGPluginManager.fileURL(id))
        self.commit()
    }

    func install(source rawSource: String) -> InstallResult {
        let source = rawSource.trimmingCharacters(in: .whitespacesAndNewlines)
        if source.isEmpty {
            return .failed("Буфер обмена пуст. Скопируй текст плагина и попробуй снова.")
        }
        if source.utf8.count > 200_000 {
            return .failed("Плагин слишком большой.")
        }
        let header = GGPluginManager.parseHeader(source)
        let name = header.name ?? "Плагин"
        let id = "p" + GGPluginManager.shortHash(name)

        let result = self.evaluate(source: source, id: id)
        if let error = result.error {
            return .failed("Ошибка в плагине: " + error)
        }
        do {
            try source.write(to: GGPluginManager.fileURL(id), atomically: true, encoding: .utf8)
        } catch {
            return .failed("Не удалось сохранить плагин.")
        }

        let entry = Entry(id: id, name: name, version: header.version, info: header.info, enabled: true)
        var updated = false
        if let index = self.entries.firstIndex(where: { $0.id == id }) {
            self.entries[index] = entry
            updated = true
        } else {
            self.entries.append(entry)
        }
        self.contexts[id] = result.context
        self.errors[id] = nil
        self.commit()
        return .installed(entry, updated: updated)
    }

    private func commit() {
        if let data = try? JSONEncoder().encode(self.entries) {
            let _ = try? data.write(to: GGPluginManager.indexURL, options: .atomic)
        }
        self.revision += 1
        self.changePipe.putNext(self.revision)
    }

    // MARK: Running

    /// Runs the `onSendMessage` handlers of every enabled plugin, in the order of installation.
    func transformOutgoing(_ text: String) -> SendOutcome {
        var current = text
        var changed = false
        for entry in self.entries where entry.enabled {
            guard let context = self.runtimeContext(for: entry) else {
                continue
            }
            self.errors[entry.id] = nil
            guard let api = context.objectForKeyedSubscript("motanavi"), let result = api.invokeMethod("__runSend", withArguments: [current]) else {
                continue
            }
            if result.isBoolean && !result.toBool() {
                return .cancelled
            }
            if result.isString, let value = result.toString(), value != current {
                current = value
                changed = true
            }
        }
        return changed ? .replaced(current) : .unchanged
    }

    private func runtimeContext(for entry: Entry) -> JSContext? {
        if let existing = self.contexts[entry.id] {
            return existing
        }
        guard let source = try? String(contentsOf: GGPluginManager.fileURL(entry.id), encoding: .utf8) else {
            self.errors[entry.id] = "файл плагина не найден"
            return nil
        }
        let result = self.evaluate(source: source, id: entry.id)
        if let error = result.error {
            self.errors[entry.id] = error
            return nil
        }
        self.contexts[entry.id] = result.context
        return result.context
    }

    private func evaluate(source: String, id: String) -> (context: JSContext?, error: String?) {
        guard let context = JSContext() else {
            return (nil, "не удалось запустить JavaScript")
        }
        context.name = id

        var loadError: String?
        context.exceptionHandler = { _, exception in
            loadError = exception?.toString() ?? "неизвестная ошибка"
        }

        let logBlock: @convention(block) (String) -> Void = { message in
            GGPluginManager.appendLog("[" + id + "] " + message)
        }
        let getBlock: @convention(block) (String) -> String = { key in
            return UserDefaults.standard.string(forKey: "motanavi.plugin." + id + "." + key) ?? ""
        }
        let setBlock: @convention(block) (String, String) -> Void = { key, value in
            if value.isEmpty {
                UserDefaults.standard.removeObject(forKey: "motanavi.plugin." + id + "." + key)
            } else {
                UserDefaults.standard.set(value, forKey: "motanavi.plugin." + id + "." + key)
            }
        }
        context.setObject(unsafeBitCast(logBlock, to: AnyObject.self), forKeyedSubscript: "__log" as NSString)
        context.setObject(unsafeBitCast(getBlock, to: AnyObject.self), forKeyedSubscript: "__sget" as NSString)
        context.setObject(unsafeBitCast(setBlock, to: AnyObject.self), forKeyedSubscript: "__sset" as NSString)

        let _ = context.evaluateScript(GGPluginManager.shim)
        let _ = context.evaluateScript(source)

        if let error = loadError {
            return (nil, error)
        }
        context.exceptionHandler = { [weak self] _, exception in
            let message = exception?.toString() ?? "неизвестная ошибка"
            GGPluginManager.appendLog("[" + id + "] ошибка: " + message)
            self?.errors[id] = message
        }
        return (context, nil)
    }

    private static let shim = """
    var motanavi = (function () {
      var sendHandlers = [];
      return {
        version: "1.0",
        log: function (message) { __log(String(message)); },
        onSendMessage: function (handler) {
          if (typeof handler === "function") { sendHandlers.push(handler); }
        },
        storage: {
          get: function (key) {
            var raw = __sget(String(key));
            return raw === "" ? null : JSON.parse(raw);
          },
          set: function (key, value) {
            var raw = JSON.stringify(value);
            __sset(String(key), raw === undefined ? "" : raw);
          }
        },
        __runSend: function (text) {
          var current = text;
          for (var i = 0; i < sendHandlers.length; i++) {
            var result = sendHandlers[i](current);
            if (result === false) { return false; }
            if (typeof result === "string") { current = result; }
          }
          return current;
        }
      };
    })();
    """

    // MARK: Helpers

    private static func parseHeader(_ source: String) -> (name: String?, version: String, info: String) {
        var name: String?
        var version = ""
        var info = ""
        var lineCount = 0
        for rawLine in source.components(separatedBy: "\n") {
            lineCount += 1
            if lineCount > 40 {
                break
            }
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard line.hasPrefix("//") else {
                continue
            }
            let body = line.dropFirst(2).trimmingCharacters(in: .whitespaces)
            guard let colon = body.firstIndex(of: ":") else {
                continue
            }
            let key = body[body.startIndex..<colon].trimmingCharacters(in: .whitespaces).lowercased()
            let value = body[body.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            if value.isEmpty {
                continue
            }
            switch key {
            case "name":
                name = value
            case "version":
                version = value
            case "description":
                info = value
            default:
                break
            }
        }
        return (name, version, info)
    }

    private static func shortHash(_ text: String) -> String {
        var hash: UInt64 = 1469598103934665603
        for byte in text.utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 1099511628211
        }
        return String(hash % 100_000_000, radix: 36)
    }

    // MARK: Log

    static func appendLog(_ line: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        var text = (try? String(contentsOf: GGPluginManager.logURL, encoding: .utf8)) ?? ""
        text += stamp + " " + line + "\n"
        if text.count > 20_000 {
            text = String(text.suffix(15_000))
        }
        let _ = try? text.write(to: GGPluginManager.logURL, atomically: true, encoding: .utf8)
    }

    static func readLog() -> String {
        return (try? String(contentsOf: GGPluginManager.logURL, encoding: .utf8)) ?? ""
    }
}
'''

MODULE = r'''import Foundation
import UIKit
import SwiftSignalKit
import TelegramCore
import AccountContext
import TextFormat
import GGHooks
import GGSettingsUI

/// Entry point of the GGPlugins feature module (MotaNavi): «Ещё › Плагины».
/// A plugin is a small JavaScript text pasted from the clipboard. It can change the text of
/// outgoing messages with `motanavi.onSendMessage(function (text) { return text; })`.
public enum GGPluginsModule {
    static let tab = GGMenuTabID("more.plugins")
    static let addSection = GGMenuSectionID("more.plugins.add")
    static let listSection = GGMenuSectionID("more.plugins.list")
    static let helpSection = GGMenuSectionID("more.plugins.help")

    private static let examplePlugin = #"""
    // ==MotaNavi Plugin==
    // name: Пример: шрагг
    // version: 1.0
    // description: Заменяет :shrug: на ¯\_(ツ)_/¯ в отправляемых сообщениях
    // ==/MotaNavi==

    motanavi.onSendMessage(function (text) {
      return text.split(":shrug:").join("¯\\_(ツ)_/¯");
    });
    """#

    private static let helpText = "Плагин — это небольшой JavaScript-текст. Как добавить: скопируй текст плагина (например, из сообщения), открой этот экран и нажми «Добавить из буфера обмена».\n\nВ плагине доступно: motanavi.onSendMessage(function (text) { return новыйТекст; }) — меняет отправляемое сообщение (return false отменяет отправку), motanavi.log(\"текст\") — запись в журнал, motanavi.storage.get(ключ) и motanavi.storage.set(ключ, значение) — память плагина.\n\nПлагины не имеют доступа к сети и файлам, но могут менять то, что ты отправляешь. Добавляй только те, которые понимаешь. Форматирование (жирный и т.п.) в изменённом сообщении не сохраняется."

    /// Declares menu rows and hook handlers. Called once on the main thread from
    /// `GGFeatures.registerAll()`, before `GGHookRegistry.freeze()`.
    public static func register() {
        GGChatScreenHooks.willSendText.register({ request, proceed in
            return GGPluginsModule.interceptSend(request, proceed: proceed)
        })
        GGPluginsModule.registerMenu()
    }

    private static func interceptSend(_ request: GGComposedTextRequest, proceed: @escaping () -> Void) -> Bool {
        guard GGPluginManager.shared.hasEnabledPlugins else {
            return false
        }
        let inputText = request.state.inputText
        // Structured composer content can not be rebuilt from plain text: sent as typed.
        if chatInputContent(from: inputText) != request.state.content {
            return false
        }
        let text = inputText.string
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return false
        }
        switch GGPluginManager.shared.transformOutgoing(text) {
        case .unchanged:
            return false
        case .cancelled:
            return true
        case let .replaced(newText):
            request.replace(ChatTextInputState(inputText: NSAttributedString(string: newText)))
            proceed()
            return true
        }
    }

    private static func registerMenu() {
        GGMenuRegistry.register(
            tab: GGMenuTabDescriptor(
                id: GGPluginsModule.tab,
                parent: .category(.more),
                title: { "Плагины" },
                topView: GGMenuTopView(content: .emoji("🧩"), text: { "Свои JavaScript-плагины для MotaNavi" }),
                searchKeywords: { ["плагины", "plugins", "javascript", "скрипты"] }
            ),
            linkIn: .moreTabs,
            order: 150,
            subtitle: { "Свои JavaScript-плагины" },
            icon: .system("puzzlepiece"),
            label: { _ in
                let count = GGPluginManager.shared.entries.count
                return count > 0 ? "\(count)" : nil
            }
        )

        GGMenuRegistry.register(section: GGMenuSectionDescriptor(id: GGPluginsModule.addSection, screen: .tab(GGPluginsModule.tab), order: 100))
        GGMenuRegistry.register(section: GGMenuSectionDescriptor(id: GGPluginsModule.listSection, screen: .tab(GGPluginsModule.tab), order: 200, header: { "Установленные плагины" }))
        GGMenuRegistry.register(section: GGMenuSectionDescriptor(id: GGPluginsModule.helpSection, screen: .tab(GGPluginsModule.tab), order: 300, footer: { _ in GGPluginsModule.helpText }))

        GGMenuRegistry.register(GGMenuRow(
            id: "plugins.add",
            section: GGPluginsModule.addSection,
            order: 100,
            title: { "Добавить из буфера обмена" },
            subtitle: { "Скопируй текст плагина и нажми сюда" },
            icon: .system("doc.on.clipboard"),
            kind: .action({ context in
                switch GGPluginManager.shared.install(source: UIPasteboard.general.string ?? "") {
                case let .installed(entry, updated):
                    context.presentToast((updated ? "Плагин обновлён: " : "Плагин добавлен: ") + entry.name)
                case let .failed(reason):
                    context.presentToast(reason)
                }
            }),
            searchKeywords: { ["добавить плагин", "add plugin"] }
        ))
        GGMenuRegistry.register(GGMenuRow(
            id: "plugins.example",
            section: GGPluginsModule.addSection,
            order: 200,
            title: { "Скопировать пример плагина" },
            subtitle: { "Потом нажми «Добавить из буфера обмена»" },
            icon: .system("doc.text"),
            kind: .action({ context in
                UIPasteboard.general.string = GGPluginsModule.examplePlugin
                context.presentToast("Пример скопирован")
            })
        ))
        GGMenuRegistry.register(GGMenuRow(
            id: "plugins.copyLog",
            section: GGPluginsModule.addSection,
            order: 300,
            title: { "Скопировать журнал плагинов" },
            subtitle: { "Записи motanavi.log и ошибки" },
            icon: .system("doc.plaintext"),
            kind: .action({ context in
                let log = GGPluginManager.readLog()
                UIPasteboard.general.string = log.isEmpty ? "Журнал пуст" : log
                context.presentToast(log.isEmpty ? "Журнал пуст" : "Журнал скопирован")
            })
        ))

        GGMenuRegistry.register(dynamicRowsIn: GGPluginsModule.listSection, { _ in
            return Signal<[GGMenuRow], NoError> { subscriber in
                subscriber.putNext(GGPluginsModule.pluginRows())
                return GGPluginManager.shared.changes.start(next: { _ in
                    subscriber.putNext(GGPluginsModule.pluginRows())
                })
            }
        })
    }

    private static func pluginRows() -> [GGMenuRow] {
        var rows: [GGMenuRow] = []
        var order = 1000
        for entry in GGPluginManager.shared.entries {
            let id = entry.id
            let name = entry.name
            rows.append(GGMenuRow(
                id: "plugins.item." + id,
                section: GGPluginsModule.listSection,
                order: order,
                title: { name },
                subtitle: { GGPluginManager.shared.subtitle(for: id) },
                icon: .system("puzzlepiece"),
                kind: .action({ context in
                    let enabled = !GGPluginManager.shared.isEnabled(id)
                    GGPluginManager.shared.setEnabled(id, enabled)
                    context.presentToast(enabled ? "Плагин включён" : "Плагин выключен")
                }),
                label: { _ in
                    return GGPluginManager.shared.isEnabled(id) ? "Вкл" : "Выкл"
                }
            ))
            rows.append(GGMenuRow(
                id: "plugins.remove." + id,
                section: GGPluginsModule.listSection,
                order: order + 50,
                title: { "Удалить «" + name + "»" },
                icon: .system("trash"),
                kind: .action({ context in
                    GGPluginManager.shared.remove(id)
                    context.presentToast("Плагин удалён")
                }),
                isDestructive: true
            ))
            order += 100
        }
        return rows
    }
}
'''

# 1. Микрофон и звук в звонке независимо друг от друга
write("Ghostgram/Features/Voice/Points/TelegramAudio/GGCallMicrophone.swift", MIC)

# 2. Модуль плагинов
write("Ghostgram/Features/Plugins/BUILD", BUILD)
write("Ghostgram/Features/Plugins/Sources/GGPluginManager.swift", MANAGER)
write("Ghostgram/Features/Plugins/Sources/GGPluginsModule.swift", MODULE)

# 3. Подключение модуля к приложению
replace_once(
    "Ghostgram/Features/BUILD",
    '        "//Ghostgram/Features/RegDate:GGRegDate",\n',
    '        "//Ghostgram/Features/RegDate:GGRegDate",\n        "//Ghostgram/Features/Plugins:GGPlugins",\n',
    '"//Ghostgram/Features/Plugins:GGPlugins"')
replace_once(
    "Ghostgram/Features/Sources/GGFeatures.swift",
    "import GGRegDate\n",
    "import GGRegDate\nimport GGPlugins\n",
    "import GGPlugins")
replace_once(
    "Ghostgram/Features/Sources/GGFeatures.swift",
    "        GGRegDateModule.register()\n",
    "        GGRegDateModule.register()\n        // MotaNavi: JavaScript plugins.\n        GGPluginsModule.register()\n",
    "GGPluginsModule.register()")

print("\nГОТОВО: часть 2 применена.")
