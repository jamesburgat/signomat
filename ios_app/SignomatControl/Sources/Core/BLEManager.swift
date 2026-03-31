import Combine
import CoreBluetooth
import Foundation

final class BLEManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var status = LiveStatus.empty
    @Published var lastCommandError: String?

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private let decoder = JSONDecoder()

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: .main)
    }

    func connect() {
        guard central.state == .poweredOn else { return }
        central.scanForPeripherals(withServices: [CBUUID(string: SignomatBLE.deviceServiceUUID)], options: nil)
    }

    func disconnect() {
        if let peripheral {
            central.cancelPeripheralConnection(peripheral)
        }
    }

    func send(_ command: SignomatCommand) {
        guard let peripheral, let commandCharacteristic else { return }
        let payload = ["cmd": command.rawValue]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        peripheral.writeValue(data, for: commandCharacteristic, type: .withResponse)
        lastCommandError = nil
    }
}

extension BLEManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state == .poweredOn {
            connect()
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String : Any], rssi RSSI: NSNumber) {
        self.peripheral = peripheral
        peripheral.delegate = self
        central.stopScan()
        central.connect(peripheral, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        isConnected = true
        peripheral.discoverServices([
            CBUUID(string: SignomatBLE.deviceServiceUUID),
            CBUUID(string: SignomatBLE.sessionServiceUUID),
            CBUUID(string: SignomatBLE.diagnosticsServiceUUID)
        ])
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        isConnected = false
        status = .empty
    }
}

extension BLEManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
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
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard let characteristics = service.characteristics else { return }
        for characteristic in characteristics {
            if characteristic.uuid == CBUUID(string: SignomatBLE.commandCharacteristicUUID) {
                commandCharacteristic = characteristic
            } else {
                peripheral.setNotifyValue(true, for: characteristic)
                peripheral.readValue(for: characteristic)
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let data = characteristic.value else { return }
        apply(data, for: characteristic.uuid)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error {
            lastCommandError = error.localizedDescription
        }
    }

    private func apply(_ data: Data, for uuid: CBUUID) {
        if uuid == CBUUID(string: SignomatBLE.deviceStatusCharacteristicUUID),
           let payload = try? decoder.decode(DeviceStatusPayload.self, from: data) {
            status.merge(payload)
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
}
