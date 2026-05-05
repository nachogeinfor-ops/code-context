using System;
using System.Collections.Generic;

namespace SampleApp;

public interface IGreeter
{
    string Greet(string name);
}

public record GreetingRecord(string Greeting, string Name);

public enum Severity
{
    Info,
    Warning,
    Error,
}

public struct Point
{
    public int X;
    public int Y;
}

public class Greeter : IGreeter
{
    private readonly string _greeting;

    public Greeter(string greeting)
    {
        _greeting = greeting;
    }

    public string Greet(string name)
    {
        return $"{_greeting}, {name}!";
    }

    public static string Capitalize(string s)
    {
        if (string.IsNullOrEmpty(s)) return s;
        return char.ToUpper(s[0]) + s.Substring(1);
    }
}

public static class Program
{
    public static void Main(string[] args)
    {
        var g = new Greeter("hello");
        Console.WriteLine(g.Greet("world"));
    }
}
