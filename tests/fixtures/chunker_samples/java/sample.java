import java.util.List;

public interface IShape {
    double area();
}

public enum Color {
    RED,
    GREEN,
    BLUE;
}

public record Point(int x, int y) {
}

public class Calculator implements IShape {
    private final double value;

    public Calculator(double value) {
        this.value = value;
    }

    public double area() {
        return value * value;
    }

    public static double add(double a, double b) {
        return a + b;
    }
}
