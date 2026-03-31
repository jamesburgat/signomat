import Foundation

enum SignomatBLE {
    static let deviceServiceUUID = "7B1E0001-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let sessionServiceUUID = "7B1E0002-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let diagnosticsServiceUUID = "7B1E0003-5D1F-4AA0-9A7D-6F5C0B6C1000"

    static let deviceStatusCharacteristicUUID = "7B1E1001-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let sessionStateCharacteristicUUID = "7B1E1002-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let commandCharacteristicUUID = "7B1E1003-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let detectionSummaryCharacteristicUUID = "7B1E1004-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let uploadSummaryCharacteristicUUID = "7B1E1005-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let storageStatusCharacteristicUUID = "7B1E1006-5D1F-4AA0-9A7D-6F5C0B6C1000"
    static let gpsStatusCharacteristicUUID = "7B1E1007-5D1F-4AA0-9A7D-6F5C0B6C1000"
}

struct DeviceStatusPayload: Codable {
    var ble: Bool
    var inf: Bool
    var sync: String
    var tempC: Double?

    enum CodingKeys: String, CodingKey {
        case ble
        case inf
        case sync
        case tempC = "temp_c"
    }
}

struct SessionStatePayload: Codable {
    var trip: Bool
    var rec: Bool
    var tripID: String?
    var det: Int

    enum CodingKeys: String, CodingKey {
        case trip
        case rec
        case tripID = "trip_id"
        case det
    }
}

struct DetectionSummaryPayload: Codable {
    var det: Int
    var last: String?
    var lastTS: String?

    enum CodingKeys: String, CodingKey {
        case det
        case last
        case lastTS = "last_ts"
    }
}

struct UploadSummaryPayload: Codable {
    var queue: Int
    var sync: String
}

struct StorageStatusPayload: Codable {
    var freeMB: Int
    var usedMB: Int
    var totalMB: Int

    enum CodingKeys: String, CodingKey {
        case freeMB = "free_mb"
        case usedMB = "used_mb"
        case totalMB = "total_mb"
    }
}

struct GPSStatusPayload: Codable {
    var gps: String
    var fix: Bool
    var lat: Double?
    var lon: Double?
    var spd: Double?
    var head: Double?
}

struct LiveStatus {
    var ble = false
    var trip = false
    var rec = false
    var inf = false
    var tripID: String?
    var det = 0
    var last: String?
    var lastTS: String?
    var queue = 0
    var gps = "idle"
    var gpsFix = false
    var freeMB = 0
    var usedMB = 0
    var totalMB = 0
    var tempC: Double?
    var sync = "idle"
    var lat: Double?
    var lon: Double?
    var spd: Double?
    var head: Double?

    static let empty = LiveStatus()

    mutating func merge(_ payload: DeviceStatusPayload) {
        ble = payload.ble
        inf = payload.inf
        sync = payload.sync
        tempC = payload.tempC
    }

    mutating func merge(_ payload: SessionStatePayload) {
        trip = payload.trip
        rec = payload.rec
        tripID = payload.tripID
        det = payload.det
    }

    mutating func merge(_ payload: DetectionSummaryPayload) {
        det = payload.det
        last = payload.last
        lastTS = payload.lastTS
    }

    mutating func merge(_ payload: UploadSummaryPayload) {
        queue = payload.queue
        sync = payload.sync
    }

    mutating func merge(_ payload: StorageStatusPayload) {
        freeMB = payload.freeMB
        usedMB = payload.usedMB
        totalMB = payload.totalMB
    }

    mutating func merge(_ payload: GPSStatusPayload) {
        gps = payload.gps
        gpsFix = payload.fix
        lat = payload.lat
        lon = payload.lon
        spd = payload.spd
        head = payload.head
    }
}

enum SignomatCommand: String, CaseIterable, Identifiable {
    case startTrip = "start_trip"
    case stopTrip = "stop_trip"
    case startRecording = "start_recording"
    case stopRecording = "stop_recording"
    case enableInference = "enable_inference"
    case disableInference = "disable_inference"
    case saveDiagnosticSnapshot = "save_diagnostic_snapshot"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .startTrip: return "Start Trip"
        case .stopTrip: return "Stop Trip"
        case .startRecording: return "Start Recording"
        case .stopRecording: return "Stop Recording"
        case .enableInference: return "Enable Inference"
        case .disableInference: return "Disable Inference"
        case .saveDiagnosticSnapshot: return "Save Diagnostic Snapshot"
        }
    }
}
