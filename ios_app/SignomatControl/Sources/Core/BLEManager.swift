import Combine
import CoreBluetooth
import CoreLocation
import Foundation
import UserNotifications

final class BLEManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var isScanning = false
    @Published var status = LiveStatus.empty
    @Published var bluetoothState = "Starting"
    @Published var connectionState = "Idle"
    @Published var discoveredPeripheralName: String?
    @Published var lastEvent = "Waiting for Bluetooth"
    @Published var lastCommandError: String?
    @Published var tripBreadcrumbs: [TripBreadcrumb] = []

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private let decoder = JSONDecoder()
    private var scanTimeoutWorkItem: DispatchWorkItem?
    private var lastNotifiedAlertID: String?

    override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func connect() {
        guard central.state == .poweredOn else {
            connectionState = "Bluetooth unavailable"
            lastEvent = "Bluetooth state is \(describe(central.state))"
            return
        }
        if let peripheral, peripheral.state == .connected {
            isConnected = true
            connectionState = "Connected"
            lastEvent = "Already connected to \(peripheral.name ?? "Pi")"
            return
        }

        lastCommandError = nil
        discoveredPeripheralName = nil
        connectionState = "Scanning"
        lastEvent = "Scanning for Signomat Pi"
        isScanning = true
        central.stopScan()
        central.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: false]
        )
        scheduleScanTimeout()
    }

    func disconnect() {
        cancelScanTimeout()
        central.stopScan()
        isScanning = false
        connectionState = "Disconnecting"
        if let peripheral {
            central.cancelPeripheralConnection(peripheral)
        }
    }

    func clearTripBreadcrumbs() {
        tripBreadcrumbs = []
        lastEvent = "Cleared map trail"
    }

    func send(_ command: SignomatCommand) {
        guard let peripheral, let commandCharacteristic else {
            lastCommandError = "Not connected to the Pi command characteristic yet."
            lastEvent = "Command blocked: no command characteristic"
            return
        }
        let payload = ["cmd": command.rawValue]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else {
            lastCommandError = "Failed to encode command payload."
            return
        }
        peripheral.writeValue(data, for: commandCharacteristic, type: .withResponse)
        lastCommandError = nil
    }
}

extension BLEManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        bluetoothState = describe(central.state)
        switch central.state {
        case .poweredOn:
            connectionState = isConnected ? "Connected" : "Ready"
            lastEvent = "Bluetooth powered on"
        case .poweredOff:
            connectionState = "Bluetooth off"
            lastEvent = "Turn Bluetooth on for Signomat"
        case .unauthorized:
            connectionState = "Bluetooth permission needed"
            lastEvent = "Allow Bluetooth access in iPhone Settings"
        case .unsupported:
            connectionState = "Bluetooth unsupported"
            lastEvent = "This device does not support BLE"
        case .resetting:
            connectionState = "Bluetooth resetting"
            lastEvent = "Bluetooth is resetting"
        case .unknown:
            connectionState = "Bluetooth starting"
            lastEvent = "Waiting for Bluetooth"
        @unknown default:
            connectionState = "Bluetooth unknown"
            lastEvent = "Unknown Bluetooth state"
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String : Any], rssi RSSI: NSNumber) {
        let advertisedServices = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
        let localName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let serviceMatch = advertisedServices.contains(CBUUID(string: SignomatBLE.deviceServiceUUID))
        let nameCandidate = localName ?? peripheral.name ?? ""
        let nameMatch = nameCandidate.lowercased().contains("signomat")
        guard serviceMatch || nameMatch else { return }

        cancelScanTimeout()
        self.peripheral = peripheral
        peripheral.delegate = self
        discoveredPeripheralName = nameCandidate.isEmpty ? "Unnamed peripheral" : nameCandidate
        connectionState = "Connecting"
        lastEvent = "Found \(discoveredPeripheralName ?? "Pi"), connecting"
        isScanning = false
        central.stopScan()
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        cancelScanTimeout()
        isConnected = true
        isScanning = false
        connectionState = "Discovering services"
        lastEvent = "Connected to \(peripheral.name ?? "Pi")"
        peripheral.discoverServices([
            CBUUID(string: SignomatBLE.deviceServiceUUID),
            CBUUID(string: SignomatBLE.sessionServiceUUID),
            CBUUID(string: SignomatBLE.diagnosticsServiceUUID)
        ])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        cancelScanTimeout()
        isConnected = false
        isScanning = false
        connectionState = "Connect failed"
        lastEvent = error?.localizedDescription ?? "Failed to connect"
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        cancelScanTimeout()
        isConnected = false
        isScanning = false
        status = .empty
        commandCharacteristic = nil
        connectionState = "Disconnected"
        lastEvent = error?.localizedDescription ?? "Disconnected from \(peripheral.name ?? "Pi")"
    }
}

extension BLEManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            connectionState = "Service discovery failed"
            lastEvent = error.localizedDescription
            return
        }

        guard let services = peripheral.services else { return }
        let characteristicUUIDs = [
            CBUUID(string: SignomatBLE.deviceStatusCharacteristicUUID),
            CBUUID(string: SignomatBLE.sessionStateCharacteristicUUID),
            CBUUID(string: SignomatBLE.commandCharacteristicUUID),
            CBUUID(string: SignomatBLE.detectionSummaryCharacteristicUUID),
            CBUUID(string: SignomatBLE.uploadSummaryCharacteristicUUID),
            CBUUID(string: SignomatBLE.storageStatusCharacteristicUUID),
            CBUUID(string: SignomatBLE.gpsStatusCharacteristicUUID)
        ]
        for service in services {
            peripheral.discoverCharacteristics(characteristicUUIDs, for: service)
        }
        lastEvent = "Discovering characteristics"
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error {
            connectionState = "Characteristic discovery failed"
            lastEvent = error.localizedDescription
            return
        }

        guard let characteristics = service.characteristics else { return }
        for characteristic in characteristics {
            if characteristic.uuid == CBUUID(string: SignomatBLE.commandCharacteristicUUID) {
                commandCharacteristic = characteristic
            } else {
                peripheral.setNotifyValue(true, for: characteristic)
                peripheral.readValue(for: characteristic)
            }
        }
        connectionState = commandCharacteristic == nil ? "Connected without command channel" : "Connected"
        lastEvent = "BLE link ready"
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            lastEvent = "Value update failed: \(error.localizedDescription)"
            return
        }
        guard let data = characteristic.value else { return }
        apply(data, for: characteristic.uuid)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            lastCommandError = error.localizedDescription
            lastEvent = "Command failed: \(error.localizedDescription)"
        } else {
            lastEvent = "Command sent"
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            lastEvent = "Notify failed: \(error.localizedDescription)"
        }
    }

    private func apply(_ data: Data, for uuid: CBUUID) {
        if uuid == CBUUID(string: SignomatBLE.deviceStatusCharacteristicUUID),
           let payload = try? decoder.decode(DeviceStatusPayload.self, from: data) {
            status.merge(payload)
            if payload.ble {
                lastEvent = "Pi reports BLE session active"
            }
            handleAlert(payload.alert)
            return
        }
        if uuid == CBUUID(string: SignomatBLE.sessionStateCharacteristicUUID),
           let payload = try? decoder.decode(SessionStatePayload.self, from: data) {
            handleTripTransition(from: status.tripID, to: payload.tripID, tripActive: payload.trip)
            status.merge(payload)
            return
        }
        if uuid == CBUUID(string: SignomatBLE.detectionSummaryCharacteristicUUID),
           let payload = try? decoder.decode(DetectionSummaryPayload.self, from: data) {
            status.merge(payload)
            return
        }
        if uuid == CBUUID(string: SignomatBLE.uploadSummaryCharacteristicUUID),
           let payload = try? decoder.decode(UploadSummaryPayload.self, from: data) {
            status.merge(payload)
            return
        }
        if uuid == CBUUID(string: SignomatBLE.storageStatusCharacteristicUUID),
           let payload = try? decoder.decode(StorageStatusPayload.self, from: data) {
            status.merge(payload)
            return
        }
        if uuid == CBUUID(string: SignomatBLE.gpsStatusCharacteristicUUID),
           let payload = try? decoder.decode(GPSStatusPayload.self, from: data) {
            status.merge(payload)
            appendBreadcrumbIfNeeded(payload)
        }
    }

    private func handleTripTransition(from oldTripID: String?, to newTripID: String?, tripActive: Bool) {
        if oldTripID != newTripID {
            tripBreadcrumbs = []
            if let newTripID, tripActive {
                lastEvent = "Started trail for \(newTripID)"
            }
        } else if !tripActive && !tripBreadcrumbs.isEmpty {
            lastEvent = "Trip stopped. Trail preserved in app."
        }
    }

    private func appendBreadcrumbIfNeeded(_ payload: GPSStatusPayload) {
        guard status.trip || status.tripID != nil else { return }
        guard payload.fix, let lat = payload.lat, let lon = payload.lon else { return }
        let point = CLLocationCoordinate2D(latitude: lat, longitude: lon)
        if let last = tripBreadcrumbs.last {
            let lastLocation = CLLocation(latitude: last.coordinate.latitude, longitude: last.coordinate.longitude)
            let currentLocation = CLLocation(latitude: lat, longitude: lon)
            if currentLocation.distance(from: lastLocation) < 5 {
                return
            }
        }
        tripBreadcrumbs.append(TripBreadcrumb(coordinate: point, timestamp: Date()))
    }

    private func handleAlert(_ alert: StatusAlertPayload?) {
        guard let alert else {
            lastNotifiedAlertID = nil
            return
        }
        lastEvent = "\(alert.title): \(alert.message)"
        guard alert.id != lastNotifiedAlertID else { return }
        lastNotifiedAlertID = alert.id
        let content = UNMutableNotificationContent()
        content.title = "Signomat \(alert.level.capitalized)"
        content.body = "\(alert.title): \(alert.message)"
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: "signomat-\(alert.id)",
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    private func scheduleScanTimeout() {
        cancelScanTimeout()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            if self.isConnected || !self.isScanning {
                return
            }
            self.central.stopScan()
            self.isScanning = false
            self.connectionState = "Scan timed out"
            self.lastEvent = "No Signomat Pi peripheral found. Use LightBlue or nRF Connect to confirm advertising."
        }
        scanTimeoutWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 8, execute: workItem)
    }

    private func cancelScanTimeout() {
        scanTimeoutWorkItem?.cancel()
        scanTimeoutWorkItem = nil
    }

    private func describe(_ state: CBManagerState) -> String {
        switch state {
        case .unknown:
            return "unknown"
        case .resetting:
            return "resetting"
        case .unsupported:
            return "unsupported"
        case .unauthorized:
            return "unauthorized"
        case .poweredOff:
            return "powered off"
        case .poweredOn:
            return "powered on"
        @unknown default:
            return "unknown"
        }
    }
}

extension BLEManager: UNUserNotificationCenterDelegate {
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}
