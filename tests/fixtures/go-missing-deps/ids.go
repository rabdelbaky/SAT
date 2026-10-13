package ids

import "github.com/google/uuid"

// New returns a new random UUID string.
func New() string { return uuid.NewString() }
