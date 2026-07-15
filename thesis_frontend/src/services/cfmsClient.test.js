import { describe, expect, it } from 'vitest'
import { CFMS_PROTOCOL_VERSION, CfmsClient } from './cfmsClient'

const frame = (frameId, frameType, text) => {
  const payload = new TextEncoder().encode(text)
  const bytes = new Uint8Array(5 + payload.length)
  const view = new DataView(bytes.buffer)
  view.setUint32(0, frameId, false)
  view.setUint8(4, frameType)
  bytes.set(payload, 5)
  return bytes.buffer
}

describe('CfmsClient protocol 15', () => {
  it('allocates odd client stream IDs and wraps uint32 safely', () => {
    const client = new CfmsClient()
    expect(client.getNextFrameId()).toBe(1)
    expect(client.getNextFrameId()).toBe(3)

    client.nextFrameId = 0xfffffffd
    expect(client.getNextFrameId()).toBe(0xfffffffd)
    expect(client.getNextFrameId()).toBe(1)
  })

  it('does not reuse an active stream after wrapping', () => {
    const client = new CfmsClient()
    client.streams.set(1, { queue: [], waiters: [] })
    client.nextFrameId = 1
    expect(client.getNextFrameId()).toBe(3)
  })

  it('delivers queued frames in FIFO order', async () => {
    const client = new CfmsClient()
    client.handleIncomingFrame(frame(1, 0, 'first'))
    client.handleIncomingFrame(frame(1, 0, 'second'))

    const decoder = new TextDecoder()
    expect(decoder.decode((await client.waitFrame(1)).payload)).toBe('first')
    expect(decoder.decode((await client.waitFrame(1)).payload)).toBe('second')
  })

  it('records server capabilities from both arrays and maps', () => {
    const client = new CfmsClient()
    const info = client.applyServerInfo({
      data: { protocol_version: CFMS_PROTOCOL_VERSION, capabilities: ['http_transfer', 'resume_upload'] },
    })
    expect(info.compatible).toBe(true)
    expect(client.hasCapability('http_transfer')).toBe(true)

    client.applyServerInfo({ data: { protocol_version: 14, capabilities: { http_transfer: false } } })
    expect(client.hasCapability('http_transfer')).toBe(false)
  })
})
