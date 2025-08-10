package com.reely.dto;

public class MovieWithScore {
    private final MovieDto movie;
    private final double score;
    
    public MovieWithScore(MovieDto movie, double score) {
        this.movie = movie;
        this.score = score;
    }
    
    public MovieDto getMovie() { return movie; }
    public double getScore() { return score; }
}
