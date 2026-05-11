import SwiftUI
import UIKit
import ImageIO
import UniformTypeIdentifiers

struct DetectionReviewPreview: View {
    let detection: ArchiveDetection

    @StateObject private var cropLoader = DetectionCropPreviewLoader()
    @State private var persistedCropFailed = false

    private let primarySize = CGSize(width: 132, height: 100)
    private let secondarySize = CGSize(width: 52, height: 40)

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            primaryPreview
                .frame(width: primarySize.width, height: primarySize.height)
                .clipShape(RoundedRectangle(cornerRadius: 14))

            if shouldShowSecondaryContext, detection.secondaryContextImageURLs.isEmpty == false {
                RemoteReviewImage(urls: detection.secondaryContextImageURLs, placeholder: placeholderImage)
                    .frame(width: secondarySize.width, height: secondarySize.height)
                    .background(.thinMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color.white.opacity(0.85), lineWidth: 1)
                    )
                    .padding(6)
            }
        }
        .frame(width: primarySize.width, height: primarySize.height)
        .task(id: detection.previewIdentity) {
            persistedCropFailed = false
            await cropLoader.load(for: detection)
        }
    }

    @ViewBuilder
    private var primaryPreview: some View {
        if detection.persistedCropPreviewURLs.isEmpty == false, persistedCropFailed == false {
            RemoteReviewImage(
                urls: detection.persistedCropPreviewURLs,
                placeholder: placeholderImage,
                onFailure: {
                    persistedCropFailed = true
                }
            )
        } else if let image = cropLoader.renderedImage {
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
        } else if cropLoader.isLoadingClientCrop {
            placeholderImage
        } else if detection.framePreviewFallbackURLs.isEmpty == false {
            RemoteReviewImage(urls: detection.framePreviewFallbackURLs, placeholder: placeholderImage)
        } else {
            placeholderImage
        }
    }

    private var shouldShowSecondaryContext: Bool {
        switch primaryPreviewMode {
        case .persistedCrop:
            guard let contextURL = detection.secondaryContextImageURLs.first else { return false }
            return detection.persistedCropPreviewURLs.contains(contextURL) == false
        case .renderedCrop:
            return detection.secondaryContextImageURLs.isEmpty == false
        case .fallbackFrame, .placeholder:
            return false
        }
    }

    private var primaryPreviewMode: PrimaryPreviewMode {
        if detection.persistedCropPreviewURLs.isEmpty == false, persistedCropFailed == false {
            return .persistedCrop
        }
        if cropLoader.renderedImage != nil {
            return .renderedCrop
        }
        if detection.framePreviewFallbackURLs.isEmpty == false, cropLoader.isLoadingClientCrop == false {
            return .fallbackFrame
        }
        return .placeholder
    }

    private var placeholderImage: some View {
        ZStack {
            Color.secondary.opacity(0.15)
            VStack(spacing: 6) {
                Image(systemName: "photo")
                    .foregroundStyle(.secondary)
                Text("No Cloudflare image")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private enum PrimaryPreviewMode {
    case persistedCrop
    case renderedCrop
    case fallbackFrame
    case placeholder
}

private struct RemoteReviewImage<Placeholder: View>: View {
    let urls: [URL]
    let placeholder: Placeholder
    var onFailure: (() -> Void)?

    @StateObject private var loader = RemoteReviewImageLoader()

    var body: some View {
        Group {
            if let image = loader.image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                placeholder
            }
        }
        .task(id: taskIdentity) {
            await loader.load(urls: urls)
        }
        .onChange(of: loader.didFailAll) { _, didFailAll in
            if didFailAll {
                onFailure?()
            }
        }
    }

    private var taskIdentity: String {
        urls.map(\.absoluteString).joined(separator: "|")
    }
}

@MainActor
private final class RemoteReviewImageLoader: ObservableObject {
    @Published private(set) var image: UIImage?
    @Published private(set) var didFailAll = false

    private var lastTaskIdentity: String?

    func load(urls: [URL]) async {
        let taskIdentity = urls.map(\.absoluteString).joined(separator: "|")
        guard taskIdentity.isEmpty == false else {
            image = nil
            didFailAll = true
            lastTaskIdentity = nil
            return
        }

        if lastTaskIdentity == taskIdentity, image != nil || didFailAll {
            return
        }

        lastTaskIdentity = taskIdentity
        image = nil
        didFailAll = false

        for url in urls {
            do {
                let (data, response) = try await URLSession.shared.data(from: url)
                guard Task.isCancelled == false else { return }
                if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
                    continue
                }
                guard let resolvedImage = UIImage(data: data) else {
                    continue
                }
                image = resolvedImage
                return
            } catch is CancellationError {
                return
            } catch {
                continue
            }
        }

        didFailAll = true
    }
}

@MainActor
private final class DetectionCropPreviewLoader: ObservableObject {
    @Published private(set) var renderedImage: UIImage?
    @Published private(set) var isLoadingClientCrop = false

    private var lastRequestKey: String?
    private var lastLoadFailed = false

    func load(for detection: ArchiveDetection) async {
        guard detection.persistedCropPreviewURLs.isEmpty else {
            reset()
            return
        }

        guard let request = detection.clientSideCropRequest else {
            reset()
            return
        }

        if lastRequestKey == request.identity && (renderedImage != nil || lastLoadFailed || isLoadingClientCrop) {
            return
        }

        lastRequestKey = request.identity
        lastLoadFailed = false
        renderedImage = nil
        isLoadingClientCrop = true

        do {
            let renderedData = try await DetectionCropRenderer.renderCropData(for: request)
            guard Task.isCancelled == false else { return }
            guard let image = UIImage(data: renderedData) else {
                lastLoadFailed = true
                isLoadingClientCrop = false
                return
            }
            renderedImage = image
            isLoadingClientCrop = false
        } catch is CancellationError {
            isLoadingClientCrop = false
        } catch {
            lastLoadFailed = true
            isLoadingClientCrop = false
        }
    }

    private func reset() {
        renderedImage = nil
        isLoadingClientCrop = false
        lastRequestKey = nil
        lastLoadFailed = false
    }
}

struct DetectionCropRequest: Hashable {
    let cacheKey: String
    let sourceURL: URL
    let bboxLeft: Double
    let bboxTop: Double
    let bboxRight: Double
    let bboxBottom: Double

    var identity: String {
        "\(cacheKey)|\(sourceURL.absoluteString)|\(bboxLeft)|\(bboxTop)|\(bboxRight)|\(bboxBottom)"
    }
}

private enum DetectionCropRenderer {
    private static let sourceDataCache = NSCache<NSURL, NSData>()
    private static let croppedDataCache = NSCache<NSString, NSData>()

    static func renderCropData(for request: DetectionCropRequest) async throws -> Data {
        let cacheKey = request.identity as NSString
        if let cached = croppedDataCache.object(forKey: cacheKey) {
            return Data(referencing: cached)
        }

        let sourceData = try await fetchSourceData(from: request.sourceURL)
        let croppedData = try await Task.detached(priority: .userInitiated) {
            try cropImageData(sourceData, request: request)
        }.value

        croppedDataCache.setObject(croppedData as NSData, forKey: cacheKey)
        return croppedData
    }

    private static func fetchSourceData(from url: URL) async throws -> Data {
        if let cached = sourceDataCache.object(forKey: url as NSURL) {
            return Data(referencing: cached)
        }

        let (data, response) = try await URLSession.shared.data(from: url)
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw DetectionCropError.invalidResponse
        }

        sourceDataCache.setObject(data as NSData, forKey: url as NSURL)
        return data
    }

    private static func cropImageData(_ sourceData: Data, request: DetectionCropRequest) throws -> Data {
        guard
            let imageSource = CGImageSourceCreateWithData(sourceData as CFData, nil),
            let cgImage = CGImageSourceCreateImageAtIndex(imageSource, 0, nil)
        else {
            throw DetectionCropError.decodingFailed
        }

        guard let cropRect = cropRect(for: request, imageWidth: cgImage.width, imageHeight: cgImage.height) else {
            throw DetectionCropError.invalidBounds
        }

        guard let croppedCGImage = cgImage.cropping(to: cropRect) else {
            throw DetectionCropError.cropFailed
        }

        let output = NSMutableData()
        guard
            let destination = CGImageDestinationCreateWithData(output, UTType.png.identifier as CFString, 1, nil)
        else {
            throw DetectionCropError.encodingFailed
        }

        CGImageDestinationAddImage(destination, croppedCGImage, nil)
        guard CGImageDestinationFinalize(destination) else {
            throw DetectionCropError.encodingFailed
        }

        return output as Data
    }

    private static func cropRect(
        for request: DetectionCropRequest,
        imageWidth: Int,
        imageHeight: Int
    ) -> CGRect? {
        let bounds = CGRect(x: 0, y: 0, width: imageWidth, height: imageHeight)

        let left = max(bounds.minX, min(CGFloat(request.bboxLeft), bounds.maxX))
        let right = max(bounds.minX, min(CGFloat(request.bboxRight), bounds.maxX))
        let top = max(bounds.minY, min(CGFloat(request.bboxTop), bounds.maxY))
        let bottom = max(bounds.minY, min(CGFloat(request.bboxBottom), bounds.maxY))

        let minX = floor(min(left, right))
        let maxX = ceil(max(left, right))
        let minY = floor(min(top, bottom))
        let maxY = ceil(max(top, bottom))

        let clamped = CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
            .intersection(bounds)

        guard clamped.width >= 1, clamped.height >= 1 else { return nil }
        return clamped
    }
}

private enum DetectionCropError: Error {
    case invalidResponse
    case decodingFailed
    case invalidBounds
    case cropFailed
    case encodingFailed
}
