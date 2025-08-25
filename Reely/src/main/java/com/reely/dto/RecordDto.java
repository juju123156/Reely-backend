package com.reely.dto;

import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class RecordDto {
    private Long recordId;
    private Long movieId;
    private Long memberPk;

    private String recordTicketPrice;
    private String recordMdPrice;
    private String recordScore;
    private String recordRegDt;
    private String recordModDt;
    private String recordWatchDt;
    private String delYn;
    private String recordContent;
    private String recordCinema;
    private String recordSeat;
    private String recordWith;
    private String recordTag;

    private String movieKoNm;
    private String movieEnNm;

}
