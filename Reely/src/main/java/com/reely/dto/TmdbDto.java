package com.reely.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Data Transfer Object for TMDB Person information
 * Using Lombok to reduce boilerplate code
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TmdbDto {
    /* 인물정보 */
    private boolean adult;
    private List<String> alsoKnownAs;
    private String biography;
    private String birthday;
    private String deathday;
    private int gender;
    private String homepage;
    private int id;
    private String imdbId;
    private String knownForDepartment;
    private String name;
    private String placeOfBirth;
    private double popularity;
    private String profilePath;

    @Data
    public class PersonResult {
        private boolean adult;
        private int gender;
        private int id;
        private String known_for_department;
        private String name;
        private String original_name;
        private double popularity;
        private String profile_path;
        private List<KnownFor> known_for;
    }

    @Data
    public class KnownFor {
        private String backdrop_path;
        private int id;
        private String title;
        private String original_title;
        private String overview;
        private String poster_path;
        private String media_type;
        private boolean adult;
        private String original_language;
        private List<Integer> genre_ids;
        private double popularity;
        private String release_date;
        private boolean video;
        private double vote_average;
        private int vote_count;
    }
}