// Sample Go file for tree-sitter chunker tests.
package sample

import "fmt"

type User struct {
	ID   int
	Name string
}

func FormatMessage(name string) string {
	return fmt.Sprintf("hello, %s!", name)
}

func (u *User) Display() string {
	return fmt.Sprintf("%d: %s", u.ID, u.Name)
}
