/**
 * Message ID constants for temporary message handling
 */

// Threshold for distinguishing database IDs from temporary IDs
// Database IDs are auto-incrementing integers starting from 1
// This threshold allows for 1 trillion messages before conflicts
export const MAX_DATABASE_MESSAGE_ID = 1000000000000

// Random range for temporary message ID uniqueness
export const TEMP_MESSAGE_ID_RANDOM_RANGE = 1000

/**
 * Generate a temporary positive message ID for optimistic UI updates
 * Uses current timestamp for uniqueness
 */
export const generateTempMessageId = (): number => {
  return Date.now()
}

/**
 * Generate a temporary negative message ID for transient status messages
 * Negative IDs ensure no conflict with database IDs (which are positive)
 */
export const generateTempStatusMessageId = (): number => {
  return -(Date.now() + Math.random() * TEMP_MESSAGE_ID_RANDOM_RANGE)
}

/**
 * Check if a message ID is a temporary ID
 */
export const isTempMessageId = (id: number): boolean => {
  return id < 0 || id >= MAX_DATABASE_MESSAGE_ID
}

/**
 * Check if a message ID is a real database ID
 */
export const isRealMessageId = (id: number): boolean => {
  return id > 0 && id < MAX_DATABASE_MESSAGE_ID
}
