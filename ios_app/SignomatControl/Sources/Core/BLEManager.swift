import Combine
import CoreBluetooth
import Foundation

final class BLEManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var isScanning = false
    @Published var status = LiveStatus.empty
    @Published var bluetoothState = "Starting"
    @Published var connectionState = "Idle"
    @Published var discoveredPeripheralName: String?
    @Published var lastEvent = "Waiting for Bluetooth"
    @Published var lastCommandError: String?

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private let decoder = JSONDecoder()
    private var scanTimeoutWorkItem: DispatchWorkItem?

    override init() {
        super.init()
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
            return
        }
        if uuid == CBUUID(string: SignomatBLE.sessionStateCharacteristicUUID),
           let payload = try? decoder.decode(SessionStatePayload.self, from: data) {
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
        }
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
