#include <iostream>
#include <vector>

// Forward declarations and standalone items at top level.

namespace geometry {

// Non-templated class
class Circle {
public:
    explicit Circle(double r) : radius(r) {}
    double area() const { return 3.14159 * radius * radius; }

private:
    double radius;
};

// Non-templated struct
struct Point {
    double x;
    double y;
};

// Non-templated top-level function
double distance(const Point& a, const Point& b) {
    double dx = a.x - b.x;
    double dy = a.y - b.y;
    return dx * dx + dy * dy;
}

}  // namespace geometry

// Templated class — template_declaration wraps class_specifier.
// find_definition("Stack") must resolve to this.
template <typename T>
class Stack {
public:
    void push(T val) { data.push_back(val); }
    T pop() {
        T val = data.back();
        data.pop_back();
        return val;
    }

private:
    std::vector<T> data;
};

// Templated function — template_declaration wraps function_definition.
// find_definition("identity") must resolve to this.
template <typename T>
T identity(T val) {
    return val;
}
