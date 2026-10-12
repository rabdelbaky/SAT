package calc

import "sync"

// Counter holds a lock.
type Counter struct {
	mu sync.Mutex
	n  int
}

// Show passes the lock by value, which go vet (copylocks) rejects.
func Show(c Counter) int {
	return c.n
}

// Add returns the sum of a and b.
func Add(a, b int) int {
	return a + b
}
