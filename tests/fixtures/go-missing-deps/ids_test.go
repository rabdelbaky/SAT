package ids

import "testing"

func TestNew(t *testing.T) {
	if New() == "" {
		t.Fatal("New returned an empty string")
	}
}
