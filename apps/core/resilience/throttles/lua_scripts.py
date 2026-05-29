"""Lua scripts for atomic throttle operations in Valkey.

These scripts execute as single atomic operations, preventing race conditions
under high concurrency.
"""

# Atomic throttle check-and-update (per-user/per-scope)
# Uses a sorted set for O(log n) performance instead of O(n) list scan.
# Returns: [allowed (0/1), current_count, ttl]
THROTTLE_LUA_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local cutoff = now - window

-- Remove expired entries
redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)

-- Count remaining entries in the window
local count = redis.call('ZCARD', key)

if count >= limit then
    local ttl = redis.call('TTL', key)
    if ttl < 0 then ttl = window end
    return {0, count, ttl}
end

-- Add new entry with score=timestamp, member=timestamp:random for uniqueness
redis.call('ZADD', key, now, tostring(now) .. ':' .. tostring(math.random(1000000)))
redis.call('EXPIRE', key, window)

return {1, count + 1, window}
"""

# Sliding window counter for global throttling (O(1) performance)
# Returns: [allowed (0/1), effective_count, ttl]
GLOBAL_THROTTLE_LUA_SCRIPT = """
local key_prefix = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local window_start = math.floor(now / window) * window
local window_position = (now - window_start) / window

local current_key = key_prefix .. ':' .. tostring(math.floor(window_start))
local previous_key = key_prefix .. ':' .. tostring(math.floor(window_start - window))

local current_count = tonumber(redis.call('GET', current_key) or '0')
local previous_count = tonumber(redis.call('GET', previous_key) or '0')

local effective_count = current_count + previous_count * (1 - window_position)

if effective_count >= limit then
    local ttl = window - (now - window_start)
    return {0, math.ceil(effective_count), math.ceil(ttl)}
end

redis.call('INCR', current_key)
redis.call('EXPIRE', current_key, window * 2)

return {1, math.ceil(effective_count) + 1, math.ceil(window - (now - window_start))}
"""
